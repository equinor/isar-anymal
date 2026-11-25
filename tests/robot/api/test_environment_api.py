from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture
from requests import RequestException, Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
    RobotCommunicationException,
)

from isar_anymal.config import settings
from isar_anymal.robot.api.api import API
from isar_anymal.robot.api.environment_api import EnvironmentAPI
from isar_anymal.robot.api.mission_planner import MissionPlanner
from isar_anymal.robot.api.request_handler import RequestHandler
from tests.robot.utilities import (
    _mock_response_object,
    build_acoustic_task,
    waypoint_graph_payload,
)


@pytest.fixture
def api(mocker: MockerFixture) -> EnvironmentAPI:
    mocker.patch.object(settings, "SERVER_URL", "https://server")
    mocker.patch.object(settings, "ENVIRONMENT_MAP_ID", "map-id")
    return EnvironmentAPI(Mock(spec=RequestHandler))


@pytest.mark.parametrize("server_url", ["https://server", "https://server/"])
def test_waypoint_graph_uses_shared_server_and_parses_references(
    api: EnvironmentAPI, mocker: MockerFixture, server_url: str
):
    mocker.patch.object(settings, "SERVER_URL", server_url)
    api.request_handler.get.return_value = _mock_response_object(
        waypoint_graph_payload()
    )
    graph = api.get_waypoint_graph()
    api.request_handler.get.assert_called_once_with(
        url="https://server/environment-api/maps/map-id/waypoints/graph", params=None
    )
    assert graph.nodes[1].position == (10, 0, 10)
    assert graph.edges[0].start_pose.id == "a"


@pytest.mark.parametrize(
    "invalid",
    [
        "empty",
        "missing-node",
        "duplicate-node",
        "wrong-map",
        "wrong-frame",
        "missing-position",
        "nonfinite",
    ],
)
def test_invalid_graph_fails_before_mission_preparation(
    api: EnvironmentAPI, invalid: str
):
    payload = waypoint_graph_payload()
    if invalid == "empty":
        payload["edges"] = []
    elif invalid == "missing-node":
        payload["edges"][0]["startPose"]["id"] = "missing"
    elif invalid == "duplicate-node":
        payload["nodes"].append(payload["nodes"][0])
    elif invalid == "wrong-map":
        payload["nodes"][0]["mapId"] = "another-map"
    elif invalid == "wrong-frame":
        payload["nodes"][0]["frameId"] = "odom"
    elif invalid == "missing-position":
        del payload["nodes"][0]["positionX"]
    else:
        payload["nodes"][0]["positionX"] = float("nan")
    api.request_handler.get.return_value = _mock_response_object(payload)
    with pytest.raises(RobotAPIException):
        api.get_waypoint_graph()
    api.request_handler.post.assert_not_called()


def test_missing_map_id_does_not_send_requests(
    api: EnvironmentAPI, mocker: MockerFixture
):
    mocker.patch.object(settings, "ENVIRONMENT_MAP_ID", "")
    with pytest.raises(RobotAPIException, match="ANYMAL_ENVIRONMENT_MAP_ID"):
        api.get_waypoint_graph()
    api.request_handler.get.assert_not_called()


def test_api_posts_task_array_and_encodes_identifiers(api: EnvironmentAPI):
    tasks = [
        {"label": "first", "missionTaskPlugin": "docking_behavior_plugins::Undock"},
        {
            "label": "second",
            "missionTaskPlugin": "visual_inspection_simple_behavior_plugins::Inspect",
            "actionId": "action-id",
        },
    ]
    api.request_handler.post.return_value = _mock_response_object(
        [{"id": "one", "label": "first"}, {"id": "two", "label": "second"}]
    )
    result = api.create_tasks("mission/id", tasks)
    api.request_handler.post.assert_called_once_with(
        url="https://server/environment-api/maps/map-id/missions/mission%2Fid/tasks",
        json_body=tasks,
    )
    assert [task.id for task in result] == ["one", "two"]
    api.delete_resource("points-of-interest/actions", "action/id")
    api.request_handler.delete.assert_called_once_with(
        url="https://server/environment-api/maps/map-id/points-of-interest/actions/action%2Fid"
    )


def test_cleanup_listing_reads_all_pages_before_deleting(api: EnvironmentAPI):
    api.request_handler.get.side_effect = [
        _mock_response_object(
            {"items": [{"id": "one", "label": "owner-1"}], "totalItems": 2}
        ),
        _mock_response_object(
            {"items": [{"id": "two", "label": "owner-2"}], "totalItems": 2}
        ),
    ]
    result = api.list_resources("missions", "owner-")
    assert [item.id for item in result] == ["one", "two"]
    assert [
        call.kwargs["params"]["page"] for call in api.request_handler.get.call_args_list
    ] == [1, 2]
    api.request_handler.delete.assert_not_called()


@pytest.mark.parametrize(
    "second_page",
    [
        {"items": [], "totalItems": 2},
        {"items": [{"id": "one"}], "totalItems": 2},
        {"items": [{"id": "two"}], "totalItems": 3},
    ],
)
def test_inconsistent_pages_fail_explicitly(api: EnvironmentAPI, second_page: dict):
    api.request_handler.get.side_effect = [
        _mock_response_object({"items": [{"id": "one"}], "totalItems": 2}),
        _mock_response_object(second_page),
    ]
    with pytest.raises(RobotAPIException):
        api.list_resources("missions", "owner-")


def test_transport_and_malformed_responses_are_reported(api: EnvironmentAPI):
    api.request_handler.get.side_effect = RequestException("offline")
    with pytest.raises(RobotCommunicationException, match="offline"):
        api.get_waypoint_graph()
    api.request_handler.get.side_effect = None
    response = Response()
    response._content = b"not json"
    api.request_handler.get.return_value = response
    with pytest.raises(RobotAPIException, match="Invalid API response"):
        api.get_waypoint_graph()


def test_delete_uses_existing_bearer_auth_and_accepts_no_content(mocker: MockerFixture):
    handler = RequestHandler()
    mocker.patch.object(handler, "get_token", return_value="test-token")
    response = Response()
    response.status_code = 204
    response._content = b""
    request = mocker.patch(
        "isar_anymal.robot.api.request_handler.requests.request", return_value=response
    )
    assert handler.delete("https://server/environment-api/resource") is response
    assert request.call_args.kwargs["method"] == "DELETE"
    assert request.call_args.kwargs["headers"] == {"Authorization": "Bearer test-token"}


@pytest.mark.parametrize(
    "body", [b'{"message":"resource is referenced"}', b"proxy unavailable"]
)
def test_http_errors_preserve_status_and_non_json_messages(
    mocker: MockerFixture, body: bytes
):
    handler = RequestHandler()
    mocker.patch.object(handler, "get_token", return_value="test-token")
    response = Response()
    response.status_code = 409
    response._content = body
    mocker.patch(
        "isar_anymal.robot.api.request_handler.requests.request", return_value=response
    )
    with pytest.raises(RequestException, match="HTTP 409") as error:
        handler.delete("https://server/environment-api/resource")
    assert error.value.response is response
    assert "resource is referenced" in str(error.value) or "proxy unavailable" in str(
        error.value
    )


def test_mission_preparation_uses_documented_resource_endpoints(api: EnvironmentAPI):
    writes: list[str] = []

    def get(*, url: str, **kwargs):
        if url.endswith("/waypoints/graph"):
            return _mock_response_object(waypoint_graph_payload())
        return _mock_response_object({"items": [], "totalItems": 0})

    def post(*, url: str, json_body):
        path = url.split("/maps/map-id/", 1)[1]
        writes.append(path)
        if path == "points-of-interest/navigation-goals":
            return _mock_response_object({"id": "nav-id", **json_body})
        if path == "points-of-interest/actions":
            return _mock_response_object({"id": "action-id", **json_body})
        if path == "missions":
            return _mock_response_object({"id": "mission-id", "tasks": [], **json_body})
        assert path == "missions/mission-id/tasks"
        return _mock_response_object(
            [
                {"id": f"task-{index}", **task}
                for index, task in reversed(list(enumerate(json_body)))
            ]
        )

    api.request_handler.get.side_effect = get
    api.request_handler.post.side_effect = post
    task = build_acoustic_task()
    inspection = API.create_inspection(task.robot_pose, task.target, task, "acoustic")
    plan = MissionPlanner(api).prepare([inspection])
    assert writes == [
        "points-of-interest/navigation-goals",
        "points-of-interest/actions",
        "missions",
        "missions/mission-id/tasks",
    ]
    assert plan.mission_id == "mission-id"
    assert plan.undock_task_id == "task-0"
    assert plan.tasks[task.id].task_id == "task-1"
    action_body = api.request_handler.post.call_args_list[1].kwargs["json_body"]
    assert action_body["environmentItem"]["navigationGoalId"] == "nav-id"
    assert plan.tasks[task.id].asset_name == action_body["config"]["name"]
    task_bodies = api.request_handler.post.call_args.kwargs["json_body"]
    assert task_bodies[1]["actionId"] == "action-id"
