import asyncio
from collections import deque
from unittest.mock import Mock

import pytest
from isar.robot.robot_monitor_mission import robot_monitor_mission
from pytest_mock import MockerFixture
from requests import Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
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
def robot(mocker: MockerFixture) -> Robot:
    # Avoid private map files and SSE threads; retain real startup/status methods.
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


def _stored_mission() -> Mission:
    return Mission(
        id="isar-run",
        name="Display name is not the robot UID",
        robot_mission_id="DiagnosticRoutine",
    )


def _response(payload: dict) -> Mock:
    response = Mock(spec=Response)
    response.json.return_value = payload
    return response


@pytest.mark.parametrize("start_status", ["CMS_OK", "CMS_ERROR_MISSION_UNKNOWN"])
def test_stored_start_bypasses_ads_and_releases_control(
    robot: Robot, mocker: MockerFixture, start_status: str
) -> None:
    mocker.patch.object(settings, "AUTO_DISABLE_PROTECTIVE_STOP", True)
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
        robot.initiate_mission(_stored_mission())
        assert robot.current_anymal_mission_id == "robot-run"
        assert robot.current_isar_mission_id == "isar-run"
        assert robot.stored_mission_running
    else:
        with pytest.raises(RobotAPIException, match="CMS_ERROR_MISSION_UNKNOWN"):
            robot.initiate_mission(_stored_mission())
        assert robot.current_anymal_mission_id is None
        assert robot.current_isar_mission_id is None
        assert not robot.stored_mission_running

    prepare.assert_not_called()
    disengage.assert_called_once_with()
    assert not robot.inspection_handler.inspections_queue
    assert not robot.inspection_handler.missions_inspection_queue
    assert [call.kwargs["url"].rsplit("/", 1)[-1] for call in post.call_args_list] == [
        "lease",
        "user-interaction-mode",
        "start-predefined",
        "release",
    ]
    assert post.call_args_list[1].kwargs["json_body"] == {
        "userInteractionMode": "UIM_AUTONOMOUS",
        "leaseId": "lease",
    }
    assert post.call_args_list[2].kwargs["json_body"] == {
        "missionDescription": {"missionUid": "DiagnosticRoutine", "startingTaskUid": ""}
    }
    assert post.call_args_list[3].kwargs["params"]["leaseId"] == "lease"


@pytest.mark.parametrize(
    "status,outcome,task_outcomes,expected",
    [
        ("MS_RUNNING", "OC_NA", [], MissionStatus.InProgress),
        ("MS_PAUSED", "OC_NA", [], MissionStatus.Paused),
        ("MS_COMPLETED", "OC_SUCCESS", [], MissionStatus.Successful),
        ("MS_COMPLETED", "OC_FAILURE", [], MissionStatus.Failed),
        ("MS_COMPLETED", "OC_NA", [], None),
        (
            "MS_COMPLETED",
            "OC_FAILURE",
            ["OC_SUCCESS", "OC_FAILURE"],
            MissionStatus.Failed,
        ),
    ],
)
def test_stored_status_uses_current_run_and_execution_id(
    robot: Robot,
    mocker: MockerFixture,
    status: str,
    outcome: str,
    task_outcomes: list[str],
    expected: MissionStatus | None,
) -> None:
    mocker.patch.object(robot.anymal, "start_mission", return_value="robot-run")
    task_lookup = mocker.patch.object(robot.anymal, "get_task_status")
    mission = _stored_mission()
    robot.initiate_mission(mission)
    assert robot.mission_status("isar-run") == MissionStatus.NotStarted
    with pytest.raises(RobotMissionStatusException):
        robot.mission_status("DiagnosticRoutine")
    event = MissionEventDto.model_validate(
        {
            "timestamp": "now",
            "metadata": {
                "robotName": "robot",
                "missionId": "DiagnosticRoutine",
                "missionRunId": "old-run",
                "missionType": "MT_PREDEFINED",
            },
            "missionSummary": {
                "status": status,
                "outcome": outcome,
                "taskSummaries": [
                    {
                        "taskId": str(index),
                        "status": "TS_COMPLETED",
                        "outcome": task_outcome,
                        "resultInterpretation": "RI_NA",
                    }
                    for index, task_outcome in enumerate(task_outcomes)
                ],
            },
        }
    )
    robot.anymal.mission_status_handler.last_mission_event = event
    assert robot.mission_status("isar-run") == MissionStatus.NotStarted
    event.metadata.mission_run_id = "robot-run"
    if expected is None:
        with pytest.raises(RobotMissionStatusException):
            robot.mission_status("isar-run")
    else:
        assert robot.mission_status("isar-run") == expected
    if status == "MS_COMPLETED":
        upload, mqtt = mocker.Mock(), mocker.Mock()

        async def monitor():
            return await asyncio.wait_for(
                robot_monitor_mission(mission, robot, upload, mqtt), timeout=1
            )

        error, completed, cancelled = asyncio.run(monitor())
        assert completed.status == (expected or MissionStatus.Failed)
        assert (error is None) == (expected == MissionStatus.Successful)
        assert not cancelled
        upload.assert_not_called()
        mqtt.publish_task_status.assert_not_called()
    task_lookup.assert_not_called()
    if task_outcomes:
        robot.stored_mission_running = False
        assert robot.mission_status("isar-run") == MissionStatus.PartiallySuccessful


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
