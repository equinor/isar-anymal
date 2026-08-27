from types import SimpleNamespace

import pytest
from alitra import Frame, Position
from pytest_mock import MockerFixture
from robot_interface.models.exceptions.robot_exceptions import (
    RobotMissionStatusException,
    RobotTaskStatusException,
)
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.status import MissionStatus, TaskStatus
from robot_interface.models.mission.task import (
    AcousticDetectionType,
    ReturnToHome,
    TakeAcousticMeasurement,
    TakeCO2Measurement,
    TakeImage,
)

from isar_anymal import Robot
from tests.robot.utilities import (
    default_robot_pose,
    mock_file_transfers,
    mock_request_handler_for_initiate_mission,
    mock_subscribe_callback_functions,
)


@pytest.mark.requires_private_test_data
def test_that_initiate_mission_is_successful_for_a_normal_mission(
    mocker: MockerFixture,
):
    mock_subscribe_callback_functions(mocker=mocker)
    robot: Robot = Robot(
        robot_name="ox", isar_id="00000000-0000-0000-0000-000000000000"
    )
    mock_file_transfers(robot=robot, mocker=mocker)
    expected_anymal_mission_id: str = mock_request_handler_for_initiate_mission(
        robot=robot
    )

    mission: Mission = Mission(
        id="id1",
        name="test_mission",
        tasks=[
            TakeImage(
                id="id2",
                robot_pose=default_robot_pose(),
                target=Position(0, 0, 0, frame=Frame("asset")),
            ),
            TakeCO2Measurement(id="id3", robot_pose=default_robot_pose()),
            TakeAcousticMeasurement(
                id="id4",
                robot_pose=default_robot_pose(),
                target=Position(0, 0, 0, frame=Frame("asset")),
                frequency_from=1000.0,
                frequency_to=2000.0,
                snr_value_threshold=3.0,
                detection_type=AcousticDetectionType.leak,
            ),
        ],
    )

    robot.initiate_mission(mission=mission)

    assert robot.current_isar_mission_id == mission.id
    assert robot.current_anymal_mission_id == expected_anymal_mission_id
    assert len(mission.tasks) == len(robot.inspection_handler.inspections_queue)
    assert len(robot.inspection_handler.missions_inspection_queue) == 1


@pytest.mark.requires_private_test_data
def test_that_return_home_mission_is_started_correctly(
    mocker: MockerFixture,
):
    mock_subscribe_callback_functions(mocker=mocker)
    robot: Robot = Robot(
        robot_name="ox", isar_id="00000000-0000-0000-0000-000000000000"
    )
    mock_file_transfers(robot=robot, mocker=mocker)
    expected_anymal_mission_id: str = mock_request_handler_for_initiate_mission(
        robot=robot
    )

    mission: Mission = Mission(
        id="id",
        name="return_home_mission",
        tasks=[ReturnToHome()],
    )

    robot.initiate_mission(mission=mission)

    assert robot.current_isar_mission_id == mission.id
    assert robot.current_anymal_mission_id == expected_anymal_mission_id
    assert len(robot.inspection_handler.inspections_queue) == 0
    assert len(robot.inspection_handler.missions_inspection_queue) == 0


def _robot_without_init(last_mission_event: object) -> Robot:
    """Build a Robot without running __init__, which needs private map data."""
    robot: Robot = object.__new__(Robot)
    robot.anymal = SimpleNamespace(
        mission_status_handler=SimpleNamespace(last_mission_event=last_mission_event)
    )
    robot.current_anymal_mission_id = "anymal-mission-id"
    robot.current_isar_mission_id = "isar-mission-id"
    robot.return_to_home_mission_running = False
    return robot


def test_that_mission_event_without_metadata_is_ignored():
    robot: Robot = _robot_without_init(SimpleNamespace(metadata=None))

    assert robot.task_status(task_id="id1") == TaskStatus.NotStarted


def _event_for_run(mission_run_id: str) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(mission_run_id=mission_run_id))


def test_that_task_status_from_a_previous_mission_run_is_ignored():
    robot: Robot = _robot_without_init(_event_for_run("an-older-mission-run"))
    robot.anymal.get_task_status = _fail_if_called

    assert robot.task_status(task_id="id1") == TaskStatus.NotStarted


def test_that_mission_status_from_a_previous_mission_run_is_ignored():
    robot: Robot = _robot_without_init(_event_for_run("an-older-mission-run"))
    robot.anymal.get_mission_status = _fail_if_called

    assert (
        robot.mission_status(mission_id="isar-mission-id") == MissionStatus.NotStarted
    )


def test_that_mission_status_for_the_current_mission_run_is_reported():
    robot: Robot = _robot_without_init(_event_for_run("anymal-mission-id"))
    robot.anymal.get_mission_status = lambda: MissionStatus.InProgress

    assert (
        robot.mission_status(mission_id="isar-mission-id") == MissionStatus.InProgress
    )


def _fail_if_called(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("status must not be read from a stale mission event")


def test_that_unexpected_task_status_error_raises_task_status_exception():
    robot: Robot = _robot_without_init(_event_for_run("anymal-mission-id"))
    robot.anymal.get_task_status = _raise_attribute_error

    with pytest.raises(RobotTaskStatusException):
        robot.task_status(task_id="id1")


def test_that_unexpected_mission_status_error_raises_mission_status_exception():
    robot: Robot = _robot_without_init(_event_for_run("anymal-mission-id"))
    robot.anymal.get_mission_status = _raise_attribute_error

    with pytest.raises(RobotMissionStatusException):
        robot.mission_status(mission_id="isar-mission-id")


def _raise_attribute_error(*_args: object, **_kwargs: object) -> None:
    raise AttributeError("'NoneType' object has no attribute 'status'")
