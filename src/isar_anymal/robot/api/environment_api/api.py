import logging
from typing import Literal
from urllib.parse import quote

from requests import RequestException, Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
    RobotCommunicationException,
)

from isar_anymal.config import settings
from isar_anymal.robot.api.environment_api.models import (
    Action,
    MissionTasks,
    NavigationGoal,
    Resource,
    ResourcePage,
    WaypointGraph,
)
from isar_anymal.robot.api.request_handler import RequestHandler, parse_response

logger = logging.getLogger(__name__)

ResourceType = Literal[
    "missions",
    "points-of-interest/actions",
    "points-of-interest/environment-items",
    "points-of-interest/navigation-goals",
]


class EnvironmentAPI:
    def __init__(self, request_handler: RequestHandler) -> None:
        self.request_handler = request_handler

    def _request(
        self,
        method: Literal["GET", "POST", "DELETE"],
        path: str,
        *,
        body: dict | list[dict] | None = None,
        params: dict | None = None,
    ) -> Response:
        base_url = f"{settings.SERVER_URL.rstrip('/')}/environment-api"
        if not settings.ENVIRONMENT_MAP_ID.strip():
            raise RobotAPIException("ANYMAL_ENVIRONMENT_MAP_ID must be configured")
        map_id = quote(settings.ENVIRONMENT_MAP_ID, safe="")
        url = f"{base_url}/maps/{map_id}/{path}"
        try:
            if method == "GET":
                return self.request_handler.get(url=url, params=params)
            if method == "POST":
                return self.request_handler.post(url=url, json_body=body)
            return self.request_handler.delete(url=url)
        except RequestException as e:
            message = f"Environment API {method} {path} failed: {e}"
            logger.error(message)
            if e.response is not None:
                raise RobotAPIException(message) from e
            raise RobotCommunicationException(message) from e

    def get_waypoint_graph(self) -> WaypointGraph:
        graph = parse_response(self._request("GET", "waypoints/graph"), WaypointGraph)
        if any(
            node.map_id != settings.ENVIRONMENT_MAP_ID or node.frame_id != "map"
            for node in graph.nodes
        ):
            raise RobotAPIException(
                "Waypoint poses must belong to the configured map and use frame 'map'"
            )
        return graph

    def list_resources(
        self, resource_type: ResourceType, label_prefix: str
    ) -> list[Resource]:
        resources: list[Resource] = []
        page = 1
        total_items: int | None = None
        while True:
            result = parse_response(
                self._request(
                    "GET",
                    resource_type,
                    params={"label": label_prefix, "page": page, "size": 1000},
                ),
                ResourcePage,
            )
            if total_items is None:
                total_items = result.total_items
            elif result.total_items != total_items:
                raise RobotAPIException(
                    f"Environment API {resource_type} changed during pagination"
                )
            resources.extend(result.items)
            if (
                len({resource.id for resource in resources}) != len(resources)
                or len(resources) > total_items
            ):
                raise RobotAPIException(
                    f"Environment API returned inconsistent pages for {resource_type}"
                )
            if len(resources) == total_items:
                return resources
            if not result.items:
                raise RobotAPIException(
                    f"Environment API returned an incomplete page for {resource_type}"
                )
            page += 1

    def create_navigation_goal(self, body: dict) -> NavigationGoal:
        return parse_response(
            self._request("POST", "points-of-interest/navigation-goals", body=body),
            NavigationGoal,
        )

    def create_action(self, body: dict) -> Action:
        return parse_response(
            self._request("POST", "points-of-interest/actions", body=body), Action
        )

    def create_mission(self, label: str) -> Resource:
        return parse_response(
            self._request("POST", "missions", body={"label": label}), Resource
        )

    def create_tasks(self, mission_id: str, tasks: list[dict]) -> list[Resource]:
        return parse_response(
            self._request(
                "POST", f"missions/{quote(mission_id, safe='')}/tasks", body=tasks
            ),
            MissionTasks,
        ).root

    def delete_resource(self, resource_type: ResourceType, resource_id: str) -> None:
        self._request("DELETE", f"{resource_type}/{quote(resource_id, safe='')}")
