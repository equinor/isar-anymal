from collections import deque
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture
from requests import Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
    RobotInfeasibleMissionException,
    RobotMissionStatusException,
)
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.status import MissionStatus

from isar_anymal import Robot
from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.api import ANYmalAPI
from isar_anymal.robot.api.anymal_api.models import MissionEventDto
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.inspection_handler import (
    InspectionHandler,
)
from isar_anymal.robot.api.api import API
from isar_anymal.robot.api.mission_status_handler import MissionStatusHandler
from isar_anymal.robot.api.request_handler import RequestHandler
from tests.robot.utilities import build_acoustic_task


@pytest.fixture
def stored_mission() -> Mission:
    return Mission(
        id="isar-run",
        name="Display name is not the robot UID",
        tasks=[],
        robot_mission_id="DiagnosticRoutine",
    )


@pytest.fixture
def robot(mocker: MockerFixture) -> Robot:
    # Avoid map files and SSE threads; exercise the real startup and status paths.
    robot = object.__new__(Robot)
    robot.anymal = object.__new__(API)
    robot.anymal.anymal_api = ANYmalAPI(mocker.Mock(spec=RequestHandler))
    robot.anymal.mission_status_handler = object.__new__(MissionStatusHandler)
    robot.anymal.mission_status_handler.last_mission_event = None
    robot.inspection_handler = object.__new__(InspectionHandler)
    robot.inspection_handler.inspections_queue = deque()
    robot.inspection_handler.missions_inspection_queue = deque()
    robot.current_anymal_mission_id = "previous-run"
    robot.current_isar_mission_id = "previous-isar-run"
    robot.return_to_home_mission_running = True
    robot.stored_mission_running = False
    mocker.patch.object(settings, "AUTO_DISABLE_PROTECTIVE_STOP", False)
    return robot


def _response(payload: dict) -> Mock:
    response = Mock(spec=Response)
    response.json.return_value = payload
    return response


@pytest.mark.parametrize("auto_disable_protective_stop", [False, True])
@pytest.mark.parametrize("start_status", ["CMS_OK", "CMS_ERROR_MISSION_UNKNOWN"])
def test_stored_mission_start_request(
    robot: Robot,
    stored_mission: Mission,
    mocker: MockerFixture,
    auto_disable_protective_stop: bool,
    start_status: str,
) -> None:
    mocker.patch.object(
        settings, "AUTO_DISABLE_PROTECTIVE_STOP", auto_disable_protective_stop
    )
    disengage = mocker.patch.object(robot.anymal, "disengage_protective_stop")
    prepare = mocker.patch.object(robot.anymal, "prepare_mission_plan")
    request_handler = robot.anymal.anymal_api.request_handler
    mocker.patch.object(
        request_handler,
        "get",
        return_value=_response(
            {
                "header": {"timestamp": "now", "status": "ASCS_OK"},
                "userInteractionMode": "UIM_MANUAL",
            }
        ),
    )
    post = mocker.patch.object(
        request_handler,
        "post",
        side_effect=[
            _response({"status": "SCS_OK", "leaseId": "lease"}),
            _response({"header": {"timestamp": "now", "status": "ASCS_OK"}}),
            _response(
                {
                    "status": "ASCS_OK",
                    "controlMissionStatus": start_status,
                    "timestamp": "now",
                    "runUid": "robot-run",
                }
            ),
            _response({"status": "SCS_OK"}),
        ],
    )

    if start_status == "CMS_OK":
        robot.initiate_stored_mission(stored_mission)
        assert robot.current_anymal_mission_id == "robot-run"
        assert robot.current_isar_mission_id == stored_mission.id
        assert robot.stored_mission_running
    else:
        with pytest.raises(RobotAPIException, match="CMS_ERROR_MISSION_UNKNOWN"):
            robot.initiate_stored_mission(stored_mission)
        assert robot.current_anymal_mission_id is None
        assert robot.current_isar_mission_id is None
        assert not robot.stored_mission_running

    assert not robot.return_to_home_mission_running
    assert robot.anymal.mission_status_handler.last_mission_event is None
    assert not robot.inspection_handler.inspections_queue
    assert not robot.inspection_handler.missions_inspection_queue
    prepare.assert_not_called()
    assert disengage.call_count == int(auto_disable_protective_stop)
    assert [call.kwargs["url"] for call in post.call_args_list] == [
        f"{settings.SERVER_URL}/anymal-api/control-authority/lease",
        f"{settings.SERVER_URL}/anymal-api/user-interaction-mode",
        f"{settings.SERVER_URL}/anymal-api/mission/start-predefined",
        f"{settings.SERVER_URL}/anymal-api/control-authority/release",
    ]
    assert post.call_args_list[1].kwargs["json_body"] == {
        "userInteractionMode": "UIM_AUTONOMOUS",
        "leaseId": "lease",
    }
    assert post.call_args_list[2].kwargs["json_body"] == {
        "missionDescription": {
            "missionUid": "DiagnosticRoutine",
            "startingTaskUid": "",
        }
    }
    assert post.call_args_list[2].kwargs["params"]["leaseId"] == "lease"
    assert post.call_args_list[3].kwargs["params"]["leaseId"] == "lease"


@pytest.mark.parametrize(
    "payload",
    [{}, {"header": {"timestamp": "now", "status": "ASCS_ERROR_PERMISSION"}}],
)
def test_stored_mission_does_not_start_if_autonomous_mode_is_not_confirmed(
    robot: Robot, stored_mission: Mission, mocker: MockerFixture, payload: dict
) -> None:
    mocker.patch.object(robot.anymal, "take_control", return_value="lease")
    release = mocker.patch.object(robot.anymal, "release_control")
    mocker.patch.object(
        robot.anymal.anymal_api, "get_user_interaction_mode", return_value="UIM_MANUAL"
    )
    mocker.patch.object(
        robot.anymal.anymal_api.request_handler,
        "post",
        return_value=_response(payload),
    )
    start = mocker.patch.object(robot.anymal.anymal_api, "start_predefined_mission")

    with pytest.raises(RobotAPIException):
        robot.initiate_stored_mission(stored_mission)

    start.assert_not_called()
    release.assert_called_once_with(lease_id="lease")
    assert robot.current_anymal_mission_id is None
    assert not robot.stored_mission_running


@pytest.mark.parametrize(
    "status,outcome,expected",
    [
        ("MS_RUNNING", "OC_NA", MissionStatus.InProgress),
        ("MS_PAUSED", "OC_NA", MissionStatus.Paused),
        ("MS_COMPLETED", "OC_SUCCESS", MissionStatus.Successful),
        ("MS_COMPLETED", "OC_FAILURE", MissionStatus.Failed),
        ("MS_COMPLETED", "OC_NORMAL", MissionStatus.Successful),
        ("MS_COMPLETED", "OC_ANOMALY", MissionStatus.Successful),
        ("MS_COMPLETED", "OC_NA", None),
        ("MS_COMPLETED", "UNRECOGNIZED", None),
    ],
)
@pytest.mark.parametrize("with_robot_tasks", [False, True])
def test_stored_mission_status(
    robot: Robot,
    stored_mission: Mission,
    mocker: MockerFixture,
    status: str,
    outcome: str,
    expected: MissionStatus | None,
    with_robot_tasks: bool,
) -> None:
    mocker.patch.object(robot.anymal, "start_mission", return_value="robot-run")
    robot.initiate_stored_mission(stored_mission)
    assert robot.mission_status(stored_mission.id) == MissionStatus.NotStarted

    event = MissionEventDto.model_validate(
        {
            "timestamp": "now",
            "metadata": {
                "robotName": "robot",
                "missionId": "DiagnosticRoutine",
                "missionRunId": "old-robot-run",
                "missionType": "MT_PREDEFINED",
            },
            "missionSummary": {
                "status": status,
                "outcome": outcome,
                "taskSummaries": (
                    [
                        {
                            "taskId": "robot-owned-diagnostic-task",
                            "status": "TS_COMPLETED",
                            "outcome": outcome,
                            "resultInterpretation": "RI_NA",
                        }
                    ]
                    if with_robot_tasks
                    else []
                ),
            },
        }
    )
    robot.anymal.mission_status_handler.last_mission_event = event
    assert robot.mission_status(stored_mission.id) == MissionStatus.NotStarted
    event.metadata.mission_run_id = "robot-run"
    if expected is None:
        with pytest.raises(RobotMissionStatusException):
            robot.mission_status(stored_mission.id)
    else:
        assert robot.mission_status(stored_mission.id) == expected


@pytest.mark.parametrize("robot_mission_id", [None, "", " ", "DiagnosticRoutine"])
def test_invalid_stored_missions_are_rejected_before_start(
    robot: Robot, mocker: MockerFixture, robot_mission_id: str | None
) -> None:
    mission = Mission.model_construct(
        id="id",
        name="invalid",
        robot_mission_id=robot_mission_id,
        tasks=(
            [build_acoustic_task()] if robot_mission_id == "DiagnosticRoutine" else []
        ),
    )
    start = mocker.patch.object(robot.anymal, "start_mission")
    with pytest.raises(RobotInfeasibleMissionException):
        robot.initiate_stored_mission(mission)
    start.assert_not_called()


@pytest.mark.parametrize("operation", ["pause", "resume", "stop"])
def test_stored_mission_controls_use_run_uid(
    robot: Robot, stored_mission: Mission, mocker: MockerFixture, operation: str
) -> None:
    mocker.patch.object(robot.anymal, "start_mission", return_value="robot-run")
    robot.initiate_stored_mission(stored_mission)
    control = mocker.patch.object(
        robot.anymal, "resume_mission" if operation == "resume" else "pause_mission"
    )

    {"pause": robot.pause, "resume": robot.resume, "stop": robot.stop}[operation]()

    control.assert_called_once_with("robot-run")
    if operation == "stop":
        assert robot.current_anymal_mission_id is None


def test_normal_mission_after_stored_mission_still_prepares_inspections(
    robot: Robot, mocker: MockerFixture
) -> None:
    robot.stored_mission_running = True
    task = build_acoustic_task()
    mission = Mission(id="normal", name="DiagnosticRoutine", tasks=[task])
    prepare = mocker.patch.object(
        robot.anymal,
        "prepare_mission_plan",
        return_value=("generated-plan", [{"name": "inspection", "label": task.id}]),
    )
    start = mocker.patch.object(robot.anymal, "start_mission", return_value="new-run")

    robot.initiate_mission(mission)

    prepare.assert_called_once_with(mission=mission)
    start.assert_called_once_with(mission_id="generated-plan")
    assert not robot.stored_mission_running
    assert list(robot.inspection_handler.inspections_queue) == [(task, "inspection")]
    assert list(robot.inspection_handler.missions_inspection_queue) == [
        ("new-run", mission)
    ]


def test_return_home_after_stored_mission_uses_dock_path(
    robot: Robot, mocker: MockerFixture
) -> None:
    robot.stored_mission_running = True
    dock = mocker.patch.object(
        robot.anymal, "start_dock_mission", return_value="dock-run"
    )
    robot.initiate_return_home("home")

    dock.assert_called_once_with()
    assert robot.current_anymal_mission_id == "dock-run"
    assert robot.current_isar_mission_id == "home"
    assert robot.return_to_home_mission_running
    assert not robot.stored_mission_running
    assert not robot.inspection_handler.inspections_queue
    assert not robot.inspection_handler.missions_inspection_queue
