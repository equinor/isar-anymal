from unittest.mock import Mock, call

import pytest
from pytest_mock import MockerFixture
from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
    RobotCommunicationException,
    RobotInfeasibleMissionException,
)
from robot_interface.models.mission.status import TaskStatus
from robot_interface.models.mission.task import (
    TakeCO2Measurement,
    TakeImage,
    TakeThermalImage,
    TakeThermalVideo,
    TakeVideo,
)

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.models import TaskSummaryDto
from isar_anymal.robot.api.api import API
from isar_anymal.robot.api.environment_api import EnvironmentAPI
from isar_anymal.robot.api.environment_api.models import (
    NavigationGoal,
    Resource,
    WaypointGraph,
)
from isar_anymal.robot.api.mission_planner import (
    RESOURCE_TYPES,
    MissionPlanner,
    closest_waypoint_position,
)
from isar_anymal.robot.api.mission_status_handler import MissionStatusHandler
from tests.robot.api.test_video_inspections import build_video_task
from tests.robot.utilities import (
    build_acoustic_task,
    default_robot_pose,
    mock_environment_api,
    waypoint_graph_payload,
)


@pytest.fixture
def environment(mocker: MockerFixture) -> Mock:
    api = Mock(spec=EnvironmentAPI)
    mock_environment_api(api, mocker)
    return api


def inspections_for_all_modalities() -> list[dict]:
    pose = default_robot_pose()
    tasks = [
        TakeImage(id="image", robot_pose=pose, target=pose.position),
        TakeThermalImage(id="thermal", robot_pose=pose, target=pose.position),
        build_video_task(TakeVideo),
        build_video_task(TakeThermalVideo).model_copy(update={"id": "thermal-video"}),
        TakeCO2Measurement(id="gas", robot_pose=pose),
        build_acoustic_task(),
    ]
    return [
        API.create_inspection(pose, pose.position, task, API.extract_task_type(task))
        for task in tasks
    ]


def test_prepares_all_modalities_and_maps_returned_ids(environment: Mock):
    inspections = inspections_for_all_modalities()
    plan = MissionPlanner(environment).prepare(inspections)
    assert plan.mission_id == "generated-mission"
    assert plan.undock_task_id == "server-task-0"
    assert set(plan.tasks) == {inspection["poi"]["name"] for inspection in inspections}
    tasks = environment.create_tasks.call_args.args[1]
    assert [task["missionTaskPlugin"] for task in tasks] == [
        "docking_behavior_plugins::Undock",
        "visual_inspection_simple_behavior_plugins::Inspect",
        "visual_inspection_thermal_behavior_plugins::Inspect",
        "visual_inspection_video_recording_behavior_plugins::Inspect",
        "visual_inspection_video_recording_behavior_plugins::Inspect",
        "gas_inspection_behavior_plugins::InspectAreaFromPose",
        "acoustic_imaging_behavior_plugins::Inspect",
    ]
    assert [task["abortOnFailure"] for task in tasks] == [
        True,
        False,
        False,
        False,
        False,
        False,
        True,
    ]
    assert plan.tasks["gas"].asset_name.endswith("-served")
    assert tasks[5]["settings"] == [
        {
            "name": "inspection_modality",
            "type": "InspectionModality",
            "value": "Gas Concentration Sensor 1",
        }
    ]
    assert (
        tasks[5]["navigationGoalId"]
        == environment.create_navigation_goal.call_args_list[4].args[0]["label"] + "-id"
    )
    for inspection, task in zip(inspections, tasks[1:]):
        assert task["label"] == inspection["poi"]["name"]
        assert plan.tasks[task["label"]].task_id != task["label"]
    for action_call, task in zip(
        environment.create_action.call_args_list, [tasks[i] for i in (1, 2, 3, 4, 6)]
    ):
        payload = action_call.args[0]
        assert payload["environmentItem"]["navigationGoalId"].endswith("-nav-id")
        assert task["actionId"] == payload["label"] + "-id"
        assert plan.tasks[task["label"]].asset_name == payload["config"]["name"]
    configs = [
        action_call.args[0]["config"]
        for action_call in environment.create_action.call_args_list
    ]
    assert configs[0]["camera_mode"] == "full_auto"
    assert configs[1]["normal_operating_range"] == {"min": -20.0, "max": 900.0}
    assert configs[1]["temperature_type"] == "Max"
    assert configs[-1]["detection_type"] == "leak"
    assert configs[-1]["frequency_from"] == 1000
    assert configs[-1]["frequency_to"] == 2000
    assert configs[-1]["roi"] == inspections[-1]["poi"]["roi"]
    environment.create_tasks.assert_called_once()


def test_cleanup_is_robot_scoped_and_dependency_ordered(environment: Mock):
    prefix = f"ISAR-{len(settings.ROBOT_NAME)}-{settings.ROBOT_NAME}-"
    environment.list_resources.side_effect = lambda kind, requested: [
        Resource(id=kind, label=f"{prefix}old"),
        Resource(id="foreign", label=f"someone-else-{prefix}old"),
        Resource(id="stored", label="Dock"),
        Resource(id="unlabelled"),
    ]
    MissionPlanner(environment).cleanup(prefix)
    assert environment.delete_resource.call_args_list == [
        call(kind, kind) for kind in RESOURCE_TYPES
    ]


def test_cleanup_conflicts_abort_without_force_or_new_writes(environment: Mock):
    prefix = f"ISAR-{len(settings.ROBOT_NAME)}-{settings.ROBOT_NAME}-"
    environment.list_resources.return_value = [Resource(id="old", label=f"{prefix}old")]
    environment.delete_resource.side_effect = RobotCommunicationException(
        "HTTP 409: in use"
    )
    with pytest.raises(RobotCommunicationException, match="in use"):
        MissionPlanner(environment).prepare(inspections_for_all_modalities())
    environment.create_navigation_goal.assert_not_called()
    environment.delete_resource.assert_called_once_with("missions", "old")


@pytest.mark.parametrize(
    "failed_operation",
    ["create_navigation_goal", "create_action", "create_mission", "create_tasks"],
)
def test_partial_creation_is_cleaned_up(
    environment: Mock, mocker: MockerFixture, failed_operation: str
):
    planner = MissionPlanner(environment)
    cleanup = mocker.patch.object(planner, "cleanup")
    getattr(environment, failed_operation).side_effect = RobotCommunicationException(
        "failed"
    )
    with pytest.raises(RobotCommunicationException, match="failed"):
        planner.prepare(inspections_for_all_modalities())
    assert cleanup.call_count == 2
    assert cleanup.call_args.args[0].startswith(cleanup.call_args_list[0].args[0])
    assert cleanup.call_args.args[0] != cleanup.call_args_list[0].args[0]


def test_rollback_failure_preserves_original_error_and_reports_cleanup(
    environment: Mock, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
):
    planner = MissionPlanner(environment)
    mocker.patch.object(
        planner,
        "cleanup",
        side_effect=[None, RobotCommunicationException("cleanup failed")],
    )
    environment.create_tasks.side_effect = RobotAPIException("task creation failed")
    with pytest.raises(RobotAPIException, match="task creation failed"):
        planner.prepare(inspections_for_all_modalities())
    assert "cleanup will be retried" in caplog.text


@pytest.mark.parametrize(
    "invalid", ["missing-label", "duplicate-label", "duplicate-id"]
)
def test_mismatched_task_response_does_not_start_a_mission(
    environment: Mock, invalid: str
):
    if invalid == "missing-label":
        environment.create_tasks.side_effect = lambda _id, tasks: [
            Resource(id=str(i)) for i, _ in enumerate(tasks)
        ]
    else:
        environment.create_tasks.side_effect = lambda _id, tasks: [
            Resource(
                id="duplicate" if invalid == "duplicate-id" else str(i),
                label=(
                    tasks[0]["label"] if invalid == "duplicate-label" else task["label"]
                ),
            )
            for i, task in enumerate(tasks)
        ]
    with pytest.raises(RobotAPIException, match="mismatched"):
        MissionPlanner(environment).prepare(inspections_for_all_modalities())


def test_gas_goal_without_served_name_is_rejected(environment: Mock):
    environment.create_navigation_goal.side_effect = None
    environment.create_navigation_goal.return_value = NavigationGoal(
        id="goal", name=None
    )
    with pytest.raises(RobotAPIException, match="no served name"):
        MissionPlanner(environment).prepare([inspections_for_all_modalities()[4]])
    environment.create_mission.assert_not_called()


def test_unsupported_or_empty_mission_does_not_mutate_map(environment: Mock):
    planner = MissionPlanner(environment)
    with pytest.raises(RobotInfeasibleMissionException, match="empty"):
        planner.prepare([])
    inspections = inspections_for_all_modalities()
    inspections[-1]["poi"]["type"] = "unsupported"
    with pytest.raises(RobotInfeasibleMissionException, match="Unsupported"):
        planner.prepare(inspections)
    environment.delete_resource.assert_not_called()
    environment.create_navigation_goal.assert_not_called()


@pytest.mark.parametrize(
    "point, expected",
    [
        ({"x": 2, "y": 4, "z": 6}, {"x": 4, "y": 0, "z": 4}),
        ({"x": -4, "y": 0, "z": -2}, {"x": 0, "y": 0, "z": 0}),
        ({"x": 12, "y": 0, "z": 14}, {"x": 10, "y": 0, "z": 10}),
    ],
)
def test_projection_preserves_height_and_clamps_to_edge(point: dict, expected: dict):
    graph = WaypointGraph.model_validate(waypoint_graph_payload())
    assert closest_waypoint_position(graph, point) == expected


def test_zero_length_waypoint_edge_is_supported():
    payload = waypoint_graph_payload()
    payload["edges"][0]["endPose"]["id"] = "a"
    graph = WaypointGraph.model_validate(payload)
    assert closest_waypoint_position(graph, {"x": 1, "y": 1, "z": 1}) == {
        "x": 0,
        "y": 0,
        "z": 0,
    }


@pytest.mark.parametrize(
    "undock_failed, expected",
    [(False, TaskStatus.Successful), (True, TaskStatus.Failed)],
)
def test_task_status_uses_server_ids_including_undock(
    mocker: MockerFixture, undock_failed: bool, expected: TaskStatus
):
    handler = object.__new__(MissionStatusHandler)
    handler.task_ids = {"isar-task": "server-task"}
    handler.undock_task_id = "server-undock"
    payload = {
        "status": "TS_COMPLETED",
        "outcome": "OC_SUCCESS",
        "resultInterpretation": "RI_NA",
    }
    mocker.patch.object(
        handler,
        "_get_anymal_task_summaries",
        return_value=[
            TaskSummaryDto.model_validate(
                {
                    **payload,
                    "taskId": "server-undock",
                    "outcome": "OC_FAILURE" if undock_failed else "OC_SUCCESS",
                }
            ),
            TaskSummaryDto.model_validate({**payload, "taskId": "server-task"}),
        ],
    )
    assert handler.get_task_status("isar-task") == expected
