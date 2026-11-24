from unittest.mock import Mock

from alitra import Frame, Orientation, Pose, Position
from pytest_mock import MockerFixture
from requests import Response
from robot_interface.models.mission.task import (
    AcousticDetectionType,
    Roi,
    TakeAcousticMeasurement,
)

from isar_anymal import Robot
from isar_anymal.config import settings
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
from isar_anymal.robot.api.environment_api import EnvironmentAPI
from isar_anymal.robot.api.environment_api.models import (
    Action,
    NavigationGoal,
    Resource,
    WaypointGraph,
)
from isar_anymal.robot.api.mission_status_handler import MissionStatusHandler


def _mock_response_object(
    json_return_value: dict | list, status_code: int = 200, text: str = ""
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


def build_acoustic_task(roi: Roi | None = None) -> TakeAcousticMeasurement:
    return TakeAcousticMeasurement(
        id="id",
        target=Position(x=1, y=1, z=1, frame=Frame("asset")),
        robot_pose=default_robot_pose(),
        frequency_from=1000.0,
        frequency_to=2000.0,
        snr_value_threshold=3.0,
        detection_type=AcousticDetectionType.leak,
        roi=roi,
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


def waypoint_graph_payload() -> dict:
    return {
        "nodes": [
            {
                "id": name,
                "frameId": "map",
                "mapId": "map-id",
                "positionX": x,
                "positionY": 0,
                "positionZ": z,
                "orientationX": 0,
                "orientationY": 0,
                "orientationZ": 0,
                "orientationW": 1,
            }
            for name, x, z in [("a", 0, 0), ("b", 10, 10)]
        ],
        "edges": [{"id": "edge", "startPose": {"id": "a"}, "endPose": {"id": "b"}}],
    }


def mock_environment_api(api: EnvironmentAPI, mocker: MockerFixture) -> None:
    mocker.patch.object(settings, "MISSION_SYNC_DELAY", 0)
    mocker.patch.object(api, "list_resources", return_value=[])
    mocker.patch.object(
        api,
        "get_waypoint_graph",
        return_value=WaypointGraph.model_validate(waypoint_graph_payload()),
    )
    mocker.patch.object(
        api,
        "create_navigation_goal",
        side_effect=lambda body: NavigationGoal(
            id=f"{body['label']}-id",
            label=body["label"],
            name=f"{body['label']}-served",
        ),
    )
    mocker.patch.object(
        api,
        "create_action",
        side_effect=lambda body: Action.model_validate(
            {"id": f"{body['label']}-id", **body}
        ),
    )
    mocker.patch.object(
        api,
        "create_mission",
        side_effect=lambda label: Resource(id="generated-mission", label=label),
    )
    mocker.patch.object(
        api,
        "create_tasks",
        side_effect=lambda mission_id, tasks: [
            Resource(id=f"server-task-{index}", label=task["label"])
            for index, task in enumerate(tasks)
        ],
    )


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
