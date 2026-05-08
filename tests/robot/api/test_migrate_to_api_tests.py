import logging
import time

import pytest


from isar_anymal.robot.api import API
from isar_anymal.robot.api.anymal_api.enums import UserInteractionMode

logger = logging.getLogger(__name__)


@pytest.mark.skip(reason="Should only be tested with hardware in the loop")
def test_start_mission_through_anymal_api() -> None:
    """How to test with physical robot
    Determine the name of a mission file which is located on the robot (can be done through the API swagger interface).
    Input the mission name in the test underneath.
    Ensure your PC is connected to the ANYmal Server correctly.
    Run test to start a mission on the robot.

    Criteria for success: Mission starts on the robot

    """
    api: API = API()

    mission_id: str = "input-relevant-mission-id-here"
    run_uid: str = api.start_mission(mission_id=mission_id)

    logger.info(f"Started mission with ID {mission_id}, received run UID: {run_uid}")


@pytest.mark.skip(reason="Should only be tested with hardware in the loop")
def test_take_and_release_control_through_anymal_api() -> None:
    """How to test with physical robot
    Run test while connected to the ANYmal Server with a physical robot.
    Observe change in control lease, preferably on tablet, while running test.

    Criteria for success: Control is taken and released on the robot without errors

    """
    api: API = API()

    lease_id: str = api.take_control()
    logger.info(f"Successfully took control of the robot and got lease ID: {lease_id}")
    logger.info("Sleeping for 5 seconds before releasing control...")
    time.sleep(5)

    api.release_control(lease_id=lease_id)
    logger.info("Successfully released control of the robot")


@pytest.mark.skip(reason="Should only be tested with hardware in the loop")
def test_get_and_set_user_interaction_mode_through_anymal_api() -> None:
    """How to test with physical robot
    Run test while connected to the ANYmal Server with a physical robot.
    Observe change in user interaction mode, preferably on tablet, while running test.
    Set mode manually to "MANUAL" on the table to observe change.

    Criteria for success: User interaction mode is retrieved and set on the robot without errors

    """
    api: API = API()

    current_mode = api.anymal_api.get_user_interaction_mode()
    logger.info(f"Current user interaction mode: {current_mode}")
    logger.info(
        "Sleeping for 5 seconds before changing user interaction mode to autonomous..."
    )
    time.sleep(5)

    api.anymal_api.set_user_interaction_mode(
        user_interaction_mode=UserInteractionMode.UIM_AUTONOMOUS,
    )
    logger.info("Successfully set user interaction mode")


@pytest.mark.skip(reason="Should only be tested with hardware in the loop")
def test_disengage_protective_stop_through_anymal_api() -> None:
    """How to test with physical robot
    Run test while connected to the ANYmal Server with a physical robot.
    First, trigger a protective stop on the robot (e.g., by pressing the emergency stop button).
    Note that this should be done while the robot is stationary, preferably laying down.
    Then run this test to disengage the protective stop via the API.

    Criteria for success: Protective stop is disengaged on the robot without errors

    """
    api: API = API()

    api.disengage_protective_stop()
    logger.info("Successfully disengaged protective stop on the robot")


@pytest.mark.skip(reason="Should only be tested with hardware in the loop")
def test_online_status_through_anymal_api() -> None:
    """How to test with physical robot
    Verify if the robot is online or not

    """
    api: API = API()

    is_online = api.robot_is_online()
    assert is_online
    logger.info("Robot is online?")


@pytest.mark.skip(reason="Should only be tested with hardware in the loop")
def test_pause_and_resume_mission_through_anymal_api() -> None:
    """How to test with physical robot
    Start a mission either manually on the robot or with the start mission test.
    Note that the start mission test logs the currently running mission UID.
    Once the robot is walking on a mission, run this test with mission UID as given above.

    PS: Might be easiest to just test this with a full scale test too.

    Criteria for success: Mission pauses, and resumes on the robot without errors

    """
    api: API = API()

    mission_run_uid: str = "input-relevant-mission-run-uid-here"
    api.pause_mission(mission_run_uid=mission_run_uid)
    logger.info("Successfully paused mission")
    logger.info("Sleeping for 10 seconds before resuming mission...")
    time.sleep(10)

    api.resume_mission(mission_run_uid=mission_run_uid)
    logger.info("Successfully resumed mission")
