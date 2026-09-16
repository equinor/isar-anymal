from collections import deque
from pathlib import Path
from unittest.mock import Mock, call

import pytest
from alitra import Frame, Position, Transform
from pydantic import ValidationError
from pytest_mock import MockerFixture
from requests import RequestException, Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotRetrieveInspectionException,
)
from robot_interface.models.inspection.inspection import (
    AcousticMeasurement,
    Image,
    ImageMetadata,
)
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.task import TASKS, TakeImage

from isar_anymal.robot.api.anymal_api.enums import InspectionMeasurementType
from isar_anymal.robot.api.anymal_api.models import (
    ConcentrationMeasurementDto,
    InspectionEventDto,
    InspectionMeasurementDto,
    ThermalMeasurementDto,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers import (
    inspection_handler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.inspection_handler import (
    _fetch_blob_via_data_navigator,
    _process_acoustic_inspection,
    _process_inspection_value,
)
from isar_anymal.robot.api.request_handler import RequestHandler
from tests.robot.utilities import build_acoustic_task, default_robot_pose


@pytest.fixture(autouse=True)
def retry_sleep(mocker: MockerFixture) -> Mock:
    return mocker.patch.object(inspection_handler.time, "sleep")


@pytest.fixture
def listing_response() -> Mock:
    response = Mock(spec=Response)
    response.json.return_value = {
        "totalItems": 1,
        "items": [{"inspection": {"filename": "image.jpg"}}],
    }
    return response


@pytest.fixture
def raw_data_response() -> Mock:
    response = Mock(spec=Response)
    response.content = b"image bytes"
    response.headers = {"content-type": "image/jpeg"}
    return response


@pytest.mark.requires_private_test_data
def test_process_acoustic_inspection(mocker: MockerFixture) -> None:
    test_data_dir: Path = Path(__file__).parent.parent.parent / "test_data"
    fixture_path: str = str(test_data_dir / "inspection_acoustic_event_example.json")
    with open(fixture_path, "r") as f:
        event: InspectionEventDto = InspectionEventDto.model_validate_json(f.read())

    listing_response: Mock = Mock(spec=Response)
    listing_response.json.return_value = {
        "totalItems": 1,
        "items": [{"inspection": {"filename": "acoustic.mp4"}}],
    }
    raw_data_response: Mock = Mock(spec=Response)
    raw_data_response.content = b"\x00\x01\x02"
    raw_data_response.headers = {"content-type": "video/mp4"}

    request_handler: Mock = Mock(spec=RequestHandler)
    request_handler.get = Mock(side_effect=[listing_response, raw_data_response])

    inspection: AcousticMeasurement = _process_acoustic_inspection(
        event=event,
        request_handler=request_handler,
        robot_pose=default_robot_pose(),
        target_position=Position(x=0, y=0, z=0, frame=Frame("asset")),
        task=build_acoustic_task(),
    )

    assert inspection.metadata.leak_rate == pytest.approx(0.5505, rel=1e-3)
    assert inspection.metadata.result == "RI_ANOMALY"
    assert inspection.metadata.frequency_from == 35000


@pytest.mark.requires_private_test_data
def test_concentration_event_parses_measurement_data() -> None:
    test_data_dir: Path = Path(__file__).parent.parent.parent / "test_data"
    fixture_path: Path = test_data_dir / "concentration_monitoring_example.json"
    event: InspectionEventDto = InspectionEventDto.model_validate_json(
        fixture_path.read_text()
    )

    assert event.measurement is not None
    assert isinstance(event.measurement.data, ConcentrationMeasurementDto)
    assert event.measurement.data.value is not None


def test_invalid_concentration_data_raises_robot_exception() -> None:
    measurement: InspectionMeasurementDto = InspectionMeasurementDto.model_construct(
        type=InspectionMeasurementType.IMT_CONCENTRATION,
        data=ThermalMeasurementDto(),
    )
    event: InspectionEventDto = InspectionEventDto.model_construct(
        measurement=measurement
    )

    with pytest.raises(RobotRetrieveInspectionException) as error:
        _process_inspection_value(event)

    assert isinstance(error.value.__cause__, ValidationError)


def test_fetch_blob_raises_on_zero_items(retry_sleep: Mock) -> None:
    listing_response: Mock = Mock(spec=Response)
    listing_response.json.return_value = {"totalItems": 0, "items": []}

    request_handler: Mock = Mock(spec=RequestHandler)
    request_handler.get = Mock(return_value=listing_response)

    with pytest.raises(RobotRetrieveInspectionException) as error:
        _fetch_blob_via_data_navigator(
            task_run_uid="task-1", request_handler=request_handler
        )

    assert "taskRunId=task-1" in error.value.error_description
    assert "after 6 attempts" in error.value.error_description
    assert request_handler.get.call_count == 6
    assert retry_sleep.call_args_list == [call(10)] * 5


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"inspection": None},
        {"inspection": {"filename": None}},
        {"inspection": {"filename": ""}},
        {"inspection": {"filename": 123}},
    ],
)
def test_fetch_blob_raises_on_malformed_item(item: dict, retry_sleep: Mock) -> None:
    listing_response: Mock = Mock(spec=Response)
    listing_response.json.return_value = {"totalItems": 1, "items": [item]}

    request_handler: Mock = Mock(spec=RequestHandler)
    request_handler.get = Mock(return_value=listing_response)

    with pytest.raises(RobotRetrieveInspectionException):
        _fetch_blob_via_data_navigator(
            task_run_uid="task-1", request_handler=request_handler
        )

    request_handler.get.assert_called_once()
    retry_sleep.assert_not_called()


@pytest.mark.parametrize("initial_result", ["empty", "request-error"])
def test_fetch_blob_waits_for_listing(
    initial_result: str,
    listing_response: Mock,
    raw_data_response: Mock,
    retry_sleep: Mock,
) -> None:
    empty = Mock(spec=Response)
    empty.json.return_value = {"totalItems": 0, "items": []}
    request_handler = Mock(spec=RequestHandler)
    request_handler.get.side_effect = [
        *(
            [empty if initial_result == "empty" else RequestException("unavailable")]
            * 5
        ),
        listing_response,
        raw_data_response,
    ]

    assert _fetch_blob_via_data_navigator("task-1", request_handler) == (
        b"image bytes",
        "jpeg",
    )
    assert request_handler.get.call_count == 7
    assert retry_sleep.call_args_list == [call(10)] * 5


@pytest.mark.parametrize("failed_stage", ["listing", "raw-data"])
def test_fetch_blob_exhausts_request_retries(
    failed_stage: str, listing_response: Mock, retry_sleep: Mock
) -> None:
    request_handler = Mock(spec=RequestHandler)
    responses = [RequestException("unavailable")] * 6
    if failed_stage == "raw-data":
        responses.insert(0, listing_response)
    request_handler.get.side_effect = responses

    with pytest.raises(RobotRetrieveInspectionException):
        _fetch_blob_via_data_navigator("task-1", request_handler)

    assert request_handler.get.call_count == len(responses)
    assert retry_sleep.call_args_list == [call(10)] * 5


def test_failed_inspection_stays_pending_then_delivers_once(
    mocker: MockerFixture,
) -> None:
    task = TakeImage(
        id="task-1",
        robot_pose=default_robot_pose(),
        target=Position(0, 0, 0, frame=Frame("asset")),
    )
    mission = Mission(id="mission-1", name="test mission", tasks=[task])
    pending: deque[tuple[TASKS, str]] = deque([(task, "asset-1")])
    event = Mock(
        spec=InspectionEventDto,
        asset_id="asset-1",
        task_run_uid="task-run-1",
        metadata=Mock(mission_run_id="run-1"),
        measurement=Mock(
            type=InspectionMeasurementType.IMT_VISUAL,
            sensor_pose=Mock(frame_id="map"),
        ),
    )
    mocker.patch.object(
        inspection_handler, "_extract_robot_pose", return_value=default_robot_pose()
    )
    mocker.patch.object(
        inspection_handler,
        "_process_inspection_blob",
        side_effect=[
            RobotRetrieveInspectionException("not available"),
            (b"image bytes", ImageMetadata, "jpeg", Image, None),
        ],
    )
    callback = Mock()

    def process() -> None:
        inspection_handler._process_inspection_event(
            event,
            pending,
            deque([("run-1", mission)]),
            Mock(spec=Transform),
            callback,
            Mock(spec=RequestHandler),
        )

    process()
    assert list(pending) == [(task, event.asset_id)]
    callback.assert_not_called()
    process()
    process()

    callback.assert_called_once()
    inspection, delivered_mission = callback.call_args.args
    assert inspection.data == b"image bytes"
    assert inspection.id == task.id
    assert delivered_mission is mission
    assert not pending
