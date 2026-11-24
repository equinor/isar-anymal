from collections import deque
from unittest.mock import Mock

import pytest
from alitra import Frame, Position, Transform
from pytest_mock import MockerFixture
from robot_interface.models.exceptions.robot_exceptions import (
    RobotInfeasibleMissionException,
    RobotRetrieveInspectionException,
)
from robot_interface.models.inspection.inspection import ThermalVideo, Video
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.task import (
    TakeImage,
    TakeThermalVideo,
    TakeVideo,
    ZoomDescription,
)

from isar_anymal.robot.api.anymal_api.enums import InspectionInterpretationType
from isar_anymal.robot.api.anymal_api.models import (
    InspectionEventDto,
    InspectionMeasurementDto,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers import (
    inspection_handler,
)
from isar_anymal.robot.api.api import API
from isar_anymal.robot.api.mission_planner import create_action_payload
from isar_anymal.robot.api.request_handler import RequestHandler
from tests.robot.utilities import build_acoustic_task, default_robot_pose


def build_video_task(
    task_class: type[TakeVideo | TakeThermalVideo] = TakeVideo,
) -> TakeVideo | TakeThermalVideo:
    return task_class(
        id="video-task",
        robot_pose=default_robot_pose(),
        target=Position(4, 5, 6, frame=Frame("asset")),
        duration=7.5,
        zoom=ZoomDescription(objectWidth=0.5, objectHeight=0.75),
    )


@pytest.fixture
def video_event() -> Mock:
    measurement = InspectionMeasurementDto.model_validate(
        {
            "type": "IMT_VIDEO",
            "sensorPose": {"frameId": "map"},
            "data": {
                "timestamp": "2026-09-17T10:00:00Z",
                "frameId": "camera",
                "cameraType": "normal",
                "digest": "digest",
                "fileSize": "1024",
                "duration": 7.25,
                "frameRate": 30,
                "width": 640,
                "height": 480,
                "fileType": "mp4",
                "fansShutoff": False,
            },
        }
    )
    return Mock(
        spec=InspectionEventDto,
        asset_id="asset-1",
        task_run_uid="task-run-1",
        metadata=Mock(mission_run_id="run-1"),
        measurement=measurement,
        interpretations=[],
    )


def create_video_action(task: TakeVideo | TakeThermalVideo) -> dict:
    inspection = API.create_inspection(
        task.robot_pose, task.target, task, API.extract_task_type(task)
    )
    return create_action_payload(inspection["poi"], "video-inspection")


def process_video_event(
    task: TakeVideo | TakeThermalVideo, event: Mock, mocker: MockerFixture
) -> Video | ThermalVideo:
    event.measurement.data.camera_type = (
        "thermal" if isinstance(task, TakeThermalVideo) else "normal"
    )
    mission = Mission(id="mission-1", name="Video mission", tasks=[task])
    mocker.patch.object(
        inspection_handler, "_extract_robot_pose", return_value=task.robot_pose
    )
    mocker.patch.object(
        inspection_handler,
        "_fetch_blob_via_data_navigator",
        return_value=(b"recorded video", "mp4"),
    )
    callback = Mock()

    inspection_handler._process_inspection_event(
        event,
        deque([(task, "asset-1")]),
        deque([("run-1", mission)]),
        Mock(spec=Transform),
        callback,
        Mock(spec=RequestHandler),
    )

    return callback.call_args.args[0]


@pytest.mark.parametrize(
    "task_class, expected_camera",
    [(TakeVideo, "normal"), (TakeThermalVideo, "thermal")],
)
def test_video_environment_selects_camera_for_task_type(
    task_class: type[TakeVideo | TakeThermalVideo],
    expected_camera: str,
) -> None:
    task = build_video_task(task_class)

    item = create_video_action(task)["config"]

    assert item["camera_type"] == expected_camera


@pytest.mark.parametrize("task_class", [TakeVideo, TakeThermalVideo])
def test_video_environment_preserves_requested_recording_duration(
    task_class: type[TakeVideo | TakeThermalVideo],
) -> None:
    task = build_video_task(task_class)
    task.duration = 12.5

    item = create_video_action(task)["config"]

    assert item["recording_duration"] == 12.5


@pytest.mark.parametrize("task_class", [TakeVideo, TakeThermalVideo])
def test_video_environment_disables_audio_recording(
    task_class: type[TakeVideo | TakeThermalVideo],
) -> None:
    task = build_video_task(task_class)

    item = create_video_action(task)["config"]

    assert item["record_audio"] is False


@pytest.mark.parametrize("task_class", [TakeVideo, TakeThermalVideo])
def test_video_environment_preserves_target_position_and_zoom(
    task_class: type[TakeVideo | TakeThermalVideo],
) -> None:
    task = build_video_task(task_class)

    action = create_video_action(task)
    pose = action["environmentItem"]["pose"]
    assert [pose[f"position{axis}"] for axis in "XYZ"] == [4, 5, 6]
    assert action["config"]["size"] == {"width": 0.5, "height": 0.75}


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_video_poi_creation_rejects_nonpositive_or_nonfinite_duration(
    duration: float,
) -> None:
    task = build_video_task()
    task.duration = duration

    with pytest.raises(RobotInfeasibleMissionException):
        API.create_inspection(task.robot_pose, task.target, task, "video")


@pytest.mark.parametrize(
    "task_class, expected_result",
    [(TakeVideo, Video), (TakeThermalVideo, ThermalVideo)],
)
def test_video_callback_returns_inspection_type_for_scheduled_task(
    task_class: type[TakeVideo | TakeThermalVideo],
    expected_result: type[Video | ThermalVideo],
    video_event: Mock,
    mocker: MockerFixture,
) -> None:
    task = build_video_task(task_class)

    inspection = process_video_event(task, video_event, mocker)

    assert isinstance(inspection, expected_result)


@pytest.mark.parametrize("task_class", [TakeVideo, TakeThermalVideo])
def test_video_callback_preserves_downloaded_video_bytes(
    task_class: type[TakeVideo | TakeThermalVideo],
    video_event: Mock,
    mocker: MockerFixture,
) -> None:
    task = build_video_task(task_class)

    inspection = process_video_event(task, video_event, mocker)

    assert inspection.data == b"recorded video"


@pytest.mark.parametrize("task_class", [TakeVideo, TakeThermalVideo])
def test_video_callback_uses_recorded_duration_instead_of_requested_duration(
    task_class: type[TakeVideo | TakeThermalVideo],
    video_event: Mock,
    mocker: MockerFixture,
) -> None:
    task = build_video_task(task_class)
    task.duration = 7.5
    video_event.measurement.data.duration = 7.25

    inspection = process_video_event(task, video_event, mocker)

    assert inspection.metadata.duration == 7.25


def test_video_blob_retrieval_wraps_malformed_measurement_in_robot_exception(
    video_event: Mock,
) -> None:
    video_event.measurement.data = {}

    with pytest.raises(RobotRetrieveInspectionException) as error:
        inspection_handler._process_inspection_blob(
            video_event, Mock(spec=RequestHandler), build_video_task()
        )

    assert "Failed to parse video measurement" in error.value.error_description


@pytest.mark.parametrize("duration", [0, float("nan")])
def test_video_blob_retrieval_rejects_nonpositive_or_nonfinite_recorded_duration(
    video_event: Mock, duration: float
) -> None:
    video_event.measurement.data.duration = duration

    with pytest.raises(RobotRetrieveInspectionException) as error:
        inspection_handler._process_inspection_blob(
            video_event, Mock(spec=RequestHandler), build_video_task()
        )

    assert "Invalid recorded video duration" in error.value.error_description


def test_video_blob_retrieval_rejects_video_received_for_image_task(
    video_event: Mock,
) -> None:
    task = TakeImage(
        id="image-task",
        robot_pose=default_robot_pose(),
        target=Position(0, 0, 0, frame=Frame("asset")),
    )

    with pytest.raises(RobotRetrieveInspectionException) as error:
        inspection_handler._process_inspection_blob(
            video_event, Mock(spec=RequestHandler), task
        )

    assert "Received video for non-video task" in error.value.error_description


def test_leak_detection_video_uses_acoustic_handler_instead_of_video_blob_handler(
    video_event: Mock, mocker: MockerFixture
) -> None:
    task = build_acoustic_task()
    mission = Mission(id="mission-1", name="Acoustic mission", tasks=[task])
    video_event.interpretations = [
        Mock(type=InspectionInterpretationType.IIT_LEAK_DETECTION)
    ]
    mocker.patch.object(
        inspection_handler, "_extract_robot_pose", return_value=task.robot_pose
    )
    acoustic = mocker.patch.object(inspection_handler, "_process_acoustic_inspection")
    blob = mocker.patch.object(inspection_handler, "_process_inspection_blob")

    inspection_handler._process_inspection_event(
        video_event,
        deque([(task, "asset-1")]),
        deque([("run-1", mission)]),
        Mock(spec=Transform),
        Mock(),
        Mock(spec=RequestHandler),
    )

    acoustic.assert_called_once()
    blob.assert_not_called()
