from collections import deque
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from alitra import Frame, Position, Transform
from dotenv import dotenv_values
from pytest_mock import MockerFixture
from requests import RequestException, Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotInfeasibleMissionException,
    RobotRetrieveInspectionException,
)
from robot_interface.models.inspection.inspection import (
    ThermalVideo,
    ThermalVideoMetadata,
    Video,
    VideoMetadata,
)
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.task import (
    TASKS,
    TakeImage,
    TakeThermalImage,
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
from isar_anymal.robot.api.request_handler import RequestHandler
from isar_anymal.robot.api.utilities.anybotics_file_handler.anymal_ads_file_transfer import (
    ANYmalADSFileTransfer,
)
from tests.robot.utilities import build_acoustic_task, default_robot_pose


@pytest.fixture(params=[TakeVideo, TakeThermalVideo])
def video_task(request: pytest.FixtureRequest) -> TakeVideo | TakeThermalVideo:
    return request.param(
        id="video-task",
        robot_pose=default_robot_pose(),
        target=Position(4, 5, 6, frame=Frame("asset")),
        duration=7.5,
        zoom=ZoomDescription(objectWidth=0.5, objectHeight=0.75),
        tag_id="tag-1",
        inspection_description="Inspect equipment",
        analysis_types=["video-analysis"],
    )


@pytest.fixture
def video_event(video_task: TakeVideo | TakeThermalVideo) -> Mock:
    measurement = InspectionMeasurementDto.model_validate(
        {
            "type": "IMT_VIDEO",
            "sensorPose": {"frameId": "map"},
            "data": {
                "timestamp": "2026-09-17T10:00:00Z",
                "frameId": "camera",
                "cameraType": (
                    "thermal" if isinstance(video_task, TakeThermalVideo) else "normal"
                ),
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


def test_video_capabilities_are_advertised() -> None:
    settings_file = Path(__file__).parents[3] / "src/isar_anymal/config/settings.env"
    capabilities = yaml.safe_load(dotenv_values(settings_file)["CAPABILITIES"])
    assert "take_video" in capabilities
    assert "take_thermal_video" in capabilities


def test_video_mission_generation(
    video_task: TakeVideo | TakeThermalVideo,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    is_thermal = isinstance(video_task, TakeThermalVideo)
    expected_type = "thermal_video" if is_thermal else "video"
    assert API.extract_task_type(video_task) == expected_type

    api = object.__new__(API)
    api.transform = Mock(spec=Transform)
    api.transform.transform_pose.return_value = video_task.robot_pose
    api.transform.transform_position.return_value = video_task.target
    inspections = api.convert_tasks_to_anymal_inspections([video_task])
    assert inspections[0]["poi"]["recording_duration"] == 7.5
    api.transform.transform_position.assert_called_once_with(
        video_task.target, from_=Frame("asset"), to_=Frame("robot")
    )

    transfer = ANYmalADSFileTransfer()
    transfer.working_folder = f"{tmp_path}/"
    mocker.patch.object(
        transfer,
        "compute_nav_goal_on_waypoints",
        return_value=(
            {"x": 1, "y": 2, "z": 3},
            [{"x": 0, "y": 0, "z": 0, "w": 1}],
        ),
    )
    environment_path, tasks = transfer.add_new_poi(
        inspections, waypoint_filepath=tmp_path / "waypoints.json"
    )
    environment = yaml.safe_load(Path(environment_path).read_text())
    item = next(
        item
        for item in environment["objects"]
        if item["type"] == "visual_inspection_video_recording"
    )
    assert item["camera_type"] == ("thermal" if is_thermal else "normal")
    assert item["recording_duration"] == 7.5
    assert item["record_audio"] is False
    assert item["size"] == {"width": 0.5, "height": 0.75}
    assert item["pose"]["pose"]["position"] == {"x": 4, "y": 5, "z": 6}
    assert tasks == [
        {"name": item["name"], "type": expected_type, "label": video_task.id}
    ]
    assert any(
        relation["parent"] == item["name"]
        for relation in environment["object_relations"]
    )

    mission_path = transfer.create_adhoc_mission("video-mission", tasks)
    mission = yaml.safe_load(Path(mission_path).read_text())
    states = next(
        setting["value"]
        for setting in mission["settings"]
        if setting["name"] == "states"
    )
    undock, recording = states
    assert recording["name"] == video_task.id
    assert recording["type"] == (
        "visual_inspection_video_recording_behavior_plugins::Inspect"
    )
    assert recording["settings"] == [
        {
            "name": "inspectable_item",
            "type": "InspectableItem",
            "value": item["name"],
        }
    ]
    assert (
        next(
            transition
            for transition in undock["transitions"]
            if transition["outcome"] == "success"
        )["transition"]
        == video_task.id
    )
    assert {
        transition["outcome"]: transition["transition"]
        for transition in recording["transitions"]
    } == {"failure": "failure", "preemption": "preemption", "success": "success"}
    assert all(
        not transition["transition_to_state"] for transition in recording["transitions"]
    )


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_invalid_video_duration_is_rejected(
    video_task: TakeVideo | TakeThermalVideo, duration: float
) -> None:
    video_task.duration = duration
    with pytest.raises(RobotInfeasibleMissionException):
        API.create_inspection(
            video_task.robot_pose,
            video_task.target,
            video_task,
            API.extract_task_type(video_task),
        )


@pytest.mark.parametrize(
    "task_class, expected_type, plugin",
    [
        (TakeImage, "visual", "visual_inspection_simple_behavior_plugins::Inspect"),
        (
            TakeThermalImage,
            "thermal",
            "visual_inspection_thermal_behavior_plugins::Inspect",
        ),
    ],
)
def test_image_mission_types_are_unchanged(task_class, expected_type, plugin) -> None:
    task = task_class(
        id="image-task",
        robot_pose=default_robot_pose(),
        target=Position(0, 0, 0, frame=Frame("asset")),
    )
    assert API.extract_task_type(task) == expected_type
    inspection = API.create_inspection(
        task.robot_pose, task.target, task, expected_type
    )
    assert "recording_duration" not in inspection["poi"]
    entry = ANYmalADSFileTransfer().create_task_entry(
        {"name": "image-poi", "type": expected_type, "label": task.id}
    )
    assert entry["type"] == plugin


def test_video_event_delivers_typed_result_once(
    video_task: TakeVideo | TakeThermalVideo,
    video_event: Mock,
    mocker: MockerFixture,
) -> None:
    listing = Mock(spec=Response)
    listing.json.return_value = {
        "totalItems": 1,
        "items": [{"inspection": {"filename": "recording.mp4"}}],
    }
    raw_data = Mock(spec=Response)
    raw_data.content = b"recorded video"
    raw_data.headers = {"content-type": "video/mp4"}
    request_handler = Mock(spec=RequestHandler)
    request_handler.get.side_effect = [listing, raw_data]
    mocker.patch.object(
        inspection_handler, "_extract_robot_pose", return_value=video_task.robot_pose
    )
    pending: deque[tuple[TASKS, str]] = deque([(video_task, "asset-1")])
    mission = Mission(id="mission-1", name="Video mission", tasks=[video_task])
    callback = Mock()

    for _ in range(2):
        inspection_handler._process_inspection_event(
            video_event,
            pending,
            deque([("run-1", mission)]),
            Mock(spec=Transform),
            callback,
            request_handler,
        )

    callback.assert_called_once()
    inspection, delivered_mission = callback.call_args.args
    expected_type = ThermalVideo if isinstance(video_task, TakeThermalVideo) else Video
    expected_metadata = (
        ThermalVideoMetadata
        if isinstance(video_task, TakeThermalVideo)
        else VideoMetadata
    )
    assert isinstance(inspection, expected_type)
    assert isinstance(inspection.metadata, expected_metadata)
    assert inspection.data == b"recorded video"
    assert inspection.id == video_task.id
    assert inspection.metadata.duration == 7.25
    assert inspection.metadata.file_type == "mp4"
    assert inspection.metadata.robot_pose == video_task.robot_pose
    assert inspection.metadata.target_position == video_task.target
    assert inspection.metadata.tag_id == video_task.tag_id
    assert (
        inspection.metadata.inspection_description == video_task.inspection_description
    )
    assert inspection.metadata.analysis_types == video_task.analysis_types
    assert delivered_mission is mission
    assert not pending
    assert request_handler.get.call_count == 2
    assert (
        request_handler.get.call_args_list[0]
        .kwargs["url"]
        .endswith("/inspections?taskRunId=task-run-1")
    )
    assert (
        request_handler.get.call_args_list[1]
        .kwargs["url"]
        .endswith("/inspections/raw-data/recording.mp4")
    )


@pytest.mark.parametrize("failure", ["download", "malformed", "zero", "nan"])
def test_failed_video_retrieval_keeps_task_pending(
    video_task: TakeVideo | TakeThermalVideo,
    video_event: Mock,
    failure: str,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocker.patch.object(
        inspection_handler, "_extract_robot_pose", return_value=video_task.robot_pose
    )
    mocker.patch.object(inspection_handler.time, "sleep")
    if failure == "malformed":
        video_event.measurement.data = {}
    elif failure in ("zero", "nan"):
        video_event.measurement.data.duration = 0 if failure == "zero" else float("nan")
    request_handler = Mock(spec=RequestHandler)
    request_handler.get.side_effect = RequestException("unavailable")
    pending: deque[tuple[TASKS, str]] = deque([(video_task, "asset-1")])
    mission = Mission(id="mission-1", name="Video mission", tasks=[video_task])
    callback = Mock()

    inspection_handler._process_inspection_event(
        video_event,
        pending,
        deque([("run-1", mission)]),
        Mock(spec=Transform),
        callback,
        request_handler,
    )

    assert list(pending) == [(video_task, "asset-1")]
    callback.assert_not_called()
    assert "Failed to retrieve inspection" in caplog.text
    assert request_handler.get.call_count == (6 if failure == "download" else 0)


def test_video_event_for_non_video_task_is_rejected(video_event: Mock) -> None:
    task = TakeImage(
        id="image-task",
        robot_pose=default_robot_pose(),
        target=Position(0, 0, 0, frame=Frame("asset")),
    )
    request_handler = Mock(spec=RequestHandler)
    with pytest.raises(RobotRetrieveInspectionException):
        inspection_handler._process_inspection_blob(video_event, request_handler, task)
    request_handler.get.assert_not_called()


def test_acoustic_video_still_uses_acoustic_handler(
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
    callback = Mock()
    pending: deque[tuple[TASKS, str]] = deque([(task, "asset-1")])

    inspection_handler._process_inspection_event(
        video_event,
        pending,
        deque([("run-1", mission)]),
        Mock(spec=Transform),
        callback,
        Mock(spec=RequestHandler),
    )

    acoustic.assert_called_once()
    blob.assert_not_called()
    callback.assert_called_once_with(acoustic.return_value, mission)
    assert not pending
