from pathlib import Path
from unittest.mock import Mock

from alitra import Pose, Position, Orientation, Frame
from pytest_mock import MockerFixture
from requests import Response

from isar_anymal import Robot
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.battery_handler import (
    BatteryHandler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.control_status_handler import (
    ControlStatusHandler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.inspection_handler import (
    InspectionHandler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.main_body_state_handler import (
    MainBodyStateHandler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.pose_handler import (
    PoseHandler,
)
from isar_anymal.robot.api.mission_status_handler import MissionStatusHandler
from isar_anymal.robot.api.utilities.anybotics_file_handler.anymal_ads_file_transfer import (
    ANYmalADSFileTransfer,
)


def _mock_response_object(
    json_return_value: dict, status_code: int = 200, text: str = ""
) -> Mock:
    mock_response: Mock = Mock(spec=Response)
    mock_response.json.return_value = json_return_value
    mock_response.status_code = status_code
    mock_response.text = text

    return mock_response


def default_robot_pose() -> Pose:
    return Pose(
        position=Position(1, 2, 3, frame=Frame("asset")),
        orientation=Orientation(0, 0, 0, 1, frame=Frame("asset")),
        frame=Frame("asset"),
    )


def mock_subscribe_callback_functions(mocker: MockerFixture) -> None:
    mocker.patch.object(
        PoseHandler,
        "register_update_pose_callback",
        return_value=None,
    )
    mocker.patch.object(
        BatteryHandler,
        "register_update_battery_callback",
        return_value=None,
    )
    mocker.patch.object(
        ControlStatusHandler,
        "register_update_control_status_callback",
        return_value=None,
    )
    mocker.patch.object(
        MissionStatusHandler,
        "register_update_mission_event_callback",
        return_value=None,
    )
    mocker.patch.object(
        InspectionHandler,
        "register_process_inspection_callback",
        return_value=None,
    )
    mocker.patch.object(
        MainBodyStateHandler,
        "_register_update_main_body_state_callback",
        return_value=None,
    )


def mock_file_transfers(robot: Robot, mocker: MockerFixture) -> None:
    test_data_dir: Path = Path(__file__).parent / "test_data"
    environment_path: str = str(test_data_dir / "environment.yaml")
    waypoint_path: str = str(test_data_dir / "waypoints.json")

    mocker.patch.object(
        ANYmalADSFileTransfer,
        "get_environment_file",
        return_value=environment_path,
    )
    mocker.patch.object(
        ANYmalADSFileTransfer,
        "get_waypoint_file",
        return_value=waypoint_path,
    )

    mocker.patch.object(
        ANYmalADSFileTransfer,
        "send_environment_file",
        return_value=True,
    )
    mocker.patch.object(
        ANYmalADSFileTransfer,
        "send_mission_file",
        return_value=True,
    )

    robot.anymal.file_transfer_handler.working_folder = str(test_data_dir) + "/"


def mock_request_handler_for_initiate_mission(robot: Robot) -> str:
    expected_lease_payload = {
        "leaseId": "c238ded5-0737-495a-9230-8c78a375240a",
        "status": "SCS_OK",
        "message": "Lease control granted successfully.",
    }
    expected_release_payload = {"status": "SCS_OK", "message": "Released successfully."}
    expected_get_user_interaction_mode_payload = {
        "header": {
            "timestamp": "1000000000",
            "status": "ASCS_OK",
            "message": "Got it.",
        },
        "userInteractionMode": "UIM_AUTONOMOUS",
    }
    expected_set_user_interaction_mode_payload = {
        "header": {"timestamp": "string", "status": "ASCS_OK", "message": "string"}
    }
    expected_disengage_protective_stop_payload = {
        "status": "SCS_OK",
        "message": "Protective stop engaged.",
    }
    expected_start_mission_payload = {
        "status": "ASCS_OK",
        "controlMissionStatus": "CMS_OK",
        "timestamp": "10000000000",
        "runUid": "fake_run_uid",
        "message": "Mission started successfully.",
    }
    lease_url = "/anymal-api/control-authority/lease"
    release_url = "/anymal-api/control-authority/release"
    set_user_interaction_mode_url = (
        "/anymal-api/control-authority/user_interaction_mode"
    )
    disengage_protective_stop_url = "/anymal-api/protective-stop/disengage"
    start_mission_url = "/anymal-api/mission/start-predefined"

    def post_side_effect(*, url: str, **kwargs):
        if url.endswith(lease_url):
            return _mock_response_object(expected_lease_payload)
        elif url.endswith(release_url):
            return _mock_response_object(expected_release_payload)
        elif url.endswith(set_user_interaction_mode_url):
            return _mock_response_object(expected_set_user_interaction_mode_payload)
        elif url.endswith(disengage_protective_stop_url):
            return _mock_response_object(expected_disengage_protective_stop_payload)
        elif url.endswith(start_mission_url):
            return _mock_response_object(expected_start_mission_payload)
        raise AssertionError(f"Unexpected url: {url}")

    robot.anymal.anymal_api.request_handler.post = Mock(side_effect=post_side_effect)
    robot.anymal.anymal_api.request_handler.get = Mock(
        return_value=_mock_response_object(expected_get_user_interaction_mode_payload)
    )

    return expected_start_mission_payload["runUid"]
