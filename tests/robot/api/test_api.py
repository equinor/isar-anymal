from pathlib import Path
from threading import Event

import pytest
from alitra import Frame, Orientation, Pose, Position
from isar.models.events import RobotAsyncEvents
from isar.robot.robot_status import RobotStatusThread
from pytest_mock import MockerFixture
from requests import ConnectionError, HTTPError, RequestException, Timeout
from robot_interface.models.exceptions.robot_exceptions import (
    RobotCommunicationException,
    RobotTelemetryNoUpdateException,
)
from robot_interface.models.inspection.inspection import Image, ImageMetadata
from robot_interface.models.mission.status import MissionStatus, RobotStatus, TaskStatus
from robot_interface.models.mission.task import Roi, TakeImage
from robot_interface.models.robots.battery_state import BatteryState
from robot_interface.robot_interface import RobotInterface

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.enums import (
    ANYmalMissionStatus,
    ANYmalTaskStatus,
    BatteryStatus,
    InspectionMeasurementType,
    Outcome,
    ResultInterpretation,
)
from isar_anymal.robot.api.anymal_api.models import (
    InspectionEventDto,
    MissionEventDto,
    TaskProgressDto,
    TaskSummaryDto,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.inspection_handler import (
    _create_blob_inspection,
)
from isar_anymal.robot.api.api import API
from isar_anymal.robot.api.mission_status_handler import MissionStatusHandler
from isar_anymal.robot.api.utilities.acoustic_roi import DEFAULT_ACOUSTIC_ROI
from tests.robot.utilities import build_acoustic_task, mock_subscribe_callback_functions


def test_create_inspection() -> None:
    robot_pose = Pose(
        position=Position(0, 0, 0, Frame("asset")),
        orientation=Orientation(x=0, y=0, z=0, w=1, frame=Frame("asset")),
        frame=Frame("asset"),
    )

    _create_blob_inspection(
        metadata_type=ImageMetadata,
        inspection_type=Image,
        robot_pose=robot_pose,
        target_position=robot_pose.position,
        file_type="jpg",
        task=TakeImage(
            id="id",
            target=Position(x=1, y=1, z=1, frame=Frame("asset")),
            robot_pose=robot_pose,
        ),
        file_bytes=b"Some file bytes",
        video_duration=None,
    )


def test_extract_task_type_acoustic() -> None:
    task = build_acoustic_task()

    assert API.extract_task_type(task) == "acoustic"


def test_create_inspection_includes_acoustic_fields() -> None:
    task = build_acoustic_task()

    poi = API.create_inspection(
        pose=task.robot_pose,
        target_position=task.target,
        task=task,
        task_type="acoustic",
    )["poi"]

    assert poi["detection_type"] == "leak"
    assert poi["frequency_from"] == 1000.0
    assert poi["frequency_to"] == 2000.0
    assert poi["snr_value_threshold"] == 3.0


def test_acoustic_poi_uses_provided_roi_when_in_bounds() -> None:
    task = build_acoustic_task(roi=Roi(x=1000, y=2000, width=500, height=500))

    poi = API.create_inspection(
        pose=task.robot_pose,
        target_position=task.target,
        task=task,
        task_type="acoustic",
    )["poi"]

    assert poi["roi"] == {"x": 1000, "y": 2000, "width": 500, "height": 500}


def test_acoustic_poi_falls_back_to_default_when_roi_is_none() -> None:
    task = build_acoustic_task(roi=None)

    poi = API.create_inspection(
        pose=task.robot_pose,
        target_position=task.target,
        task=task,
        task_type="acoustic",
    )["poi"]

    assert poi["roi"] == DEFAULT_ACOUSTIC_ROI


def test_acoustic_poi_falls_back_to_default_when_roi_out_of_bounds() -> None:
    # x=10 is below the envelope minimum (x_min=968).
    task = build_acoustic_task(roi=Roi(x=10, y=2000, width=100, height=100))

    poi = API.create_inspection(
        pose=task.robot_pose,
        target_position=task.target,
        task=task,
        task_type="acoustic",
    )["poi"]

    assert poi["roi"] == DEFAULT_ACOUSTIC_ROI


def test_create_inspection_forwards_analysis_types() -> None:
    robot_pose = Pose(
        position=Position(0, 0, 0, Frame("asset")),
        orientation=Orientation(x=0, y=0, z=0, w=1, frame=Frame("asset")),
        frame=Frame("asset"),
    )

    inspection = _create_blob_inspection(
        metadata_type=ImageMetadata,
        inspection_type=Image,
        robot_pose=robot_pose,
        target_position=robot_pose.position,
        file_type="jpg",
        task=TakeImage(
            id="id",
            target=Position(x=1, y=1, z=1, frame=Frame("asset")),
            robot_pose=robot_pose,
            analysis_types=["fencilla"],
        ),
        file_bytes=b"Some file bytes",
        video_duration=None,
    )

    assert inspection.metadata.analysis_types == ["fencilla"]


@pytest.mark.requires_private_test_data
def test_concentration_monitoring_inspection() -> None:
    test_data_dir: Path = Path(__file__).parent.parent / "test_data"
    concentration_monitoring_path: str = str(
        test_data_dir / "concentration_monitoring_example.json"
    )
    with open(concentration_monitoring_path, "r") as f:
        concentration_monitoring: str = f.read()

    inspection_event: InspectionEventDto = InspectionEventDto.model_validate_json(
        concentration_monitoring
    )
    assert (
        inspection_event.measurement.type
        == InspectionMeasurementType.IMT_CONCENTRATION_MONITORING
    )


@pytest.mark.requires_private_test_data
def test_visual_inspection() -> None:
    test_data_dir: Path = Path(__file__).parent.parent / "test_data"
    visual_inspection_path: str = str(test_data_dir / "inspection_visual_example.json")
    with open(visual_inspection_path, "r") as f:
        visual_inspection: str = f.read()

    inspection_event: InspectionEventDto = InspectionEventDto.model_validate_json(
        visual_inspection
    )
    assert inspection_event.measurement.type == InspectionMeasurementType.IMT_VISUAL


@pytest.fixture
def online_anymal(mocker: MockerFixture) -> API:
    mock_subscribe_callback_functions(mocker)
    mocker.patch.object(API, "robot_is_online", return_value=True)
    return API()


def _mission_event(mission_id: str, task_outcome: str) -> MissionEventDto:
    return MissionEventDto.model_validate(
        {
            "timestamp": "now",
            "metadata": {
                "robotName": "robot",
                "missionId": mission_id,
                "missionRunId": "run",
                "missionType": "MT_PREDEFINED",
            },
            "missionSummary": {
                "status": "MS_COMPLETED",
                "outcome": task_outcome,
                "taskSummaries": [
                    {
                        "taskId": "task",
                        "status": "TS_COMPLETED",
                        "outcome": task_outcome,
                        "resultInterpretation": "RI_NA",
                    }
                ],
            },
        }
    )


def test_robot_status_home_when_charging(online_anymal: API) -> None:
    online_anymal.battery_handler.battery.state = BatteryState.Charging
    online_anymal.battery_handler.battery.level = 50.0

    assert online_anymal.get_robot_status() == RobotStatus.Home


@pytest.mark.parametrize(
    "mission_id, task_outcome, battery_level, expected_status",
    [
        (settings.DOCK_MISSION_NAME, "OC_SUCCESS", 100.0, RobotStatus.Home),
        (settings.DOCK_MISSION_NAME, "OC_SUCCESS", 50.0, RobotStatus.Available),
        (settings.DOCK_MISSION_NAME, "OC_FAILURE", 100.0, RobotStatus.Available),
        ("Inspection", "OC_SUCCESS", 100.0, RobotStatus.Available),
    ],
)
def test_robot_status_home_when_not_charging_requires_full_battery_and_dock(
    online_anymal: API,
    mission_id: str,
    task_outcome: str,
    battery_level: float,
    expected_status: RobotStatus,
) -> None:
    online_anymal.battery_handler.battery.state = BatteryState.Normal
    online_anymal.battery_handler.battery.level = battery_level
    online_anymal.mission_status_handler.last_mission_event = _mission_event(
        mission_id, task_outcome
    )

    assert online_anymal.get_robot_status() == expected_status


def test_robot_status_not_home_when_full_without_dock(online_anymal: API) -> None:
    online_anymal.battery_handler.battery.state = BatteryState.Normal
    online_anymal.battery_handler.battery.level = 100.0

    assert online_anymal.get_robot_status() == RobotStatus.Available


def test_robot_status_home_after_successful_dock_when_battery_state_unknown(
    online_anymal: API,
) -> None:
    online_anymal.battery_handler.set_battery_state(BatteryStatus.BS_ERROR)
    online_anymal.mission_status_handler.last_mission_event = _mission_event(
        settings.DOCK_MISSION_NAME, "OC_SUCCESS"
    )

    assert online_anymal.get_robot_status() == RobotStatus.Home


def test_robot_status_raises_when_battery_state_unknown_without_dock(
    online_anymal: API,
) -> None:
    online_anymal.battery_handler.battery.level = 100.0
    online_anymal.battery_handler.set_battery_state(BatteryStatus.BS_ERROR)

    with pytest.raises(RobotTelemetryNoUpdateException, match="robot is home"):
        online_anymal.get_robot_status()


def test_control_lease_request_failure_includes_cause(
    mocker: MockerFixture,
) -> None:
    mock_subscribe_callback_functions(mocker)
    anymal = API()
    mocker.patch.object(
        anymal.request_handler, "post", side_effect=Timeout("Read timed out")
    )

    with pytest.raises(RobotCommunicationException) as exc_info:
        anymal.take_control()

    assert "Read timed out" in exc_info.value.error_description


@pytest.mark.parametrize("error_type", [ConnectionError, Timeout, HTTPError])
def test_robot_status_request_failure_raises_communication_exception(
    mocker: MockerFixture, error_type: type[RequestException]
) -> None:
    mock_subscribe_callback_functions(mocker)
    anymal = API()
    error = error_type("ANYmal Cloud unavailable")
    mocker.patch.object(anymal.request_handler, "get", side_effect=error)

    with pytest.raises(RobotCommunicationException) as exc_info:
        anymal.get_robot_status()

    assert exc_info.value.__cause__ is error
    assert settings.ROBOT_NAME in exc_info.value.error_description
    assert str(error) in exc_info.value.error_description


@pytest.mark.parametrize(
    "connection_status, expected_status",
    [
        ("CS_CONNECTED", RobotStatus.Home),
        ("CS_DISCONNECTED", RobotStatus.Offline),
    ],
)
def test_robot_status_polling_recovers_after_request_failure(
    mocker: MockerFixture, caplog, connection_status: str, expected_status: RobotStatus
) -> None:
    mock_subscribe_callback_functions(mocker)
    anymal = API()
    anymal.battery_handler.battery.state = BatteryState.Charging
    anymal.battery_handler.battery.level = 50.0
    response = mocker.Mock()
    response.json.return_value = [
        {"anymalName": settings.ROBOT_NAME, "connectionStatus": connection_status}
    ]
    request = mocker.patch.object(
        anymal.request_handler,
        "get",
        side_effect=[
            ConnectionError("Connection refused"),
            Timeout("Timed out"),
            response,
        ],
    )
    robot = mocker.Mock(spec=RobotInterface)
    robot.robot_status.side_effect = anymal.get_robot_status
    signal_exit = mocker.Mock(spec=Event)
    signal_exit.wait.side_effect = [False, False, False, True]
    events = RobotAsyncEvents()
    mocker.patch("isar.robot.robot_status.time.sleep")
    thread = RobotStatusThread(
        robot=robot, signal_exit=signal_exit, robot_async_events=events
    )

    thread.run()

    assert request.call_count == 3
    assert robot.robot_status.call_count == 3
    assert events.robot_status_update.check() == expected_status
    assert caplog.text.count("Failed to retrieve robot status:") == 2


@pytest.mark.parametrize(
    "anymal_mission_status, anymal_task_summaries, expected_mission_status",
    [
        (
            ANYmalMissionStatus.MS_RUNNING,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_ONGOING,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                )
            ],
            MissionStatus.InProgress,
        ),
        (
            ANYmalMissionStatus.MS_PAUSED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_PREEMPTED,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                )
            ],
            MissionStatus.Paused,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                )
            ],
            MissionStatus.Successful,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            MissionStatus.Successful,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            MissionStatus.Failed,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="undock",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            MissionStatus.Failed,
        ),
    ],
)
def test_get_mission_status(
    anymal_mission_status,
    anymal_task_summaries,
    expected_mission_status,
    mocker: MockerFixture,
) -> None:
    mock_subscribe_callback_functions(mocker)

    mocker.patch.object(
        MissionStatusHandler,
        "_get_anymal_mission_status",
        return_value=anymal_mission_status,
    )
    mocker.patch.object(
        MissionStatusHandler,
        "_get_anymal_task_summaries",
        return_value=anymal_task_summaries,
    )
    anymal: API = API()

    assert anymal.get_mission_status() == expected_mission_status


@pytest.mark.parametrize(
    "task_id, anymal_task_summaries, expected_task_status",
    [
        (
            "1",
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_ONGOING,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.Successful,
        ),
        (
            "2",
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_ONGOING,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.InProgress,
        ),
        (
            "2",
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.Failed,
        ),
        (
            "2",
            [
                TaskSummaryDto(
                    taskId="undock",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.Failed,
        ),
    ],
)
def test_get_task_status(
    task_id,
    anymal_task_summaries,
    expected_task_status,
    mocker: MockerFixture,
) -> None:
    mock_subscribe_callback_functions(mocker)
    mocker.patch.object(
        MissionStatusHandler,
        "_get_anymal_task_summaries",
        return_value=anymal_task_summaries,
    )
    anymal: API = API()

    assert anymal.get_task_status(task_id) == expected_task_status
