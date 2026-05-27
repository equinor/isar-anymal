from alitra import Position, Frame
import pytest
from pytest_mock import MockerFixture
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.task import (
    AcousticDetectionType,
    ReturnToHome,
    TakeAcousticMeasurement,
    TakeCO2Measurement,
    TakeImage,
)

from isar_anymal import Robot
from tests.robot.utilities import (
    mock_subscribe_callback_functions,
    mock_file_transfers,
    mock_request_handler_for_initiate_mission,
    default_robot_pose,
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
        name="test_mission",
        tasks=[
            TakeImage(
                robot_pose=default_robot_pose(),
                target=Position(0, 0, 0, frame=Frame("asset")),
            ),
            TakeCO2Measurement(robot_pose=default_robot_pose()),
            TakeAcousticMeasurement(
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
        name="return_home_mission",
        tasks=[ReturnToHome()],
    )

    robot.initiate_mission(mission=mission)

    assert robot.current_isar_mission_id == mission.id
    assert robot.current_anymal_mission_id == expected_anymal_mission_id
    assert len(robot.inspection_handler.inspections_queue) == 0
    assert len(robot.inspection_handler.missions_inspection_queue) == 0
