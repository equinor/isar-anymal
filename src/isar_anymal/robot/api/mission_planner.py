import logging
import math
from dataclasses import dataclass
from uuid import uuid4

from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
    RobotException,
    RobotInfeasibleMissionException,
)

from isar_anymal.config import settings
from isar_anymal.robot.api.environment_api import EnvironmentAPI
from isar_anymal.robot.api.environment_api.api import ResourceType
from isar_anymal.robot.api.environment_api.models import WaypointGraph

logger = logging.getLogger(__name__)

RESOURCE_TYPES: tuple[ResourceType, ...] = (
    "missions",
    "points-of-interest/actions",
    "points-of-interest/environment-items",
    "points-of-interest/navigation-goals",
)

INSPECTION_TYPES = {
    "visual": "visual_inspection_simple",
    "thermal": "visual_inspection_thermal",
    "video": "visual_inspection_video_recording",
    "thermal_video": "visual_inspection_video_recording",
    "acoustic": "acoustic_imaging",
}


@dataclass(frozen=True)
class PreparedTask:
    task_id: str
    asset_name: str


@dataclass(frozen=True)
class PreparedMission:
    mission_id: str
    tasks: dict[str, PreparedTask]
    undock_task_id: str


class MissionPlanner:
    def __init__(self, environment_api: EnvironmentAPI) -> None:
        self.environment_api = environment_api

    def prepare(self, inspections: list[dict]) -> PreparedMission:
        if not inspections:
            raise RobotInfeasibleMissionException(
                "An inspection mission cannot be empty"
            )
        labels = [inspection["poi"]["name"] for inspection in inspections]
        if len(set(labels)) != len(labels):
            raise RobotInfeasibleMissionException("Mission task IDs must be unique")

        graph = self.environment_api.get_waypoint_graph()
        owner_prefix = f"ISAR-{len(settings.ROBOT_NAME)}-{settings.ROBOT_NAME}-"
        run_label = f"{owner_prefix}{uuid4().hex}"
        payloads = []
        for index, inspection in enumerate(inspections):
            label = f"{run_label}-{index}"
            nav_goal = {
                "label": f"{label}-nav",
                "pose": create_pose(
                    closest_waypoint_position(graph, inspection["poo"]["pos"]),
                    inspection["poo"]["orientation"],
                    navigation=True,
                ),
            }
            action = (
                None
                if inspection["poi"]["type"] == "co2"
                else create_action_payload(inspection["poi"], label)
            )
            payloads.append((inspection, nav_goal, action))

        # Labels are a reserved namespace, allowing recovery after process restarts.
        self.cleanup(owner_prefix)
        try:
            tasks: list[dict] = [
                {
                    "label": f"{run_label}-undock",
                    "missionTaskPlugin": "docking_behavior_plugins::Undock",
                    "abortOnFailure": True,
                }
            ]
            asset_names: dict[str, str] = {}
            for index, (inspection, nav_payload, action_payload) in enumerate(payloads):
                poi = inspection["poi"]
                nav_goal = self.environment_api.create_navigation_goal(nav_payload)
                task = {
                    "label": poi["name"],
                    "abortOnFailure": index == len(payloads) - 1,
                }
                if action_payload is None:
                    # The API distinguishes the served gas target name from its ID.
                    if not nav_goal.name:
                        raise RobotAPIException(
                            f"Navigation goal {nav_goal.id} has no served name; "
                            "cannot correlate CO2 inspection events"
                        )
                    asset_names[poi["name"]] = nav_goal.name
                    task.update(
                        missionTaskPlugin="gas_inspection_behavior_plugins::InspectAreaFromPose",
                        navigationGoalId=nav_goal.id,
                        settings=[
                            {
                                "name": "inspection_modality",
                                "type": "InspectionModality",
                                "value": "Gas Concentration Sensor 1",
                            }
                        ],
                    )
                else:
                    action_payload["environmentItem"]["navigationGoalId"] = nav_goal.id
                    action = self.environment_api.create_action(action_payload)
                    asset_names[poi["name"]] = action.config.name
                    task.update(
                        missionTaskPlugin=f"{action_payload['actionType']}_behavior_plugins::Inspect",
                        actionId=action.id,
                    )
                tasks.append(task)

            mission = self.environment_api.create_mission(run_label)
            created_tasks = self.environment_api.create_tasks(mission.id, tasks)
            by_label = {task.label: task.id for task in created_tasks}
            if (
                len(created_tasks) != len(tasks)
                or len({task.id for task in created_tasks}) != len(tasks)
                or set(by_label) != {task["label"] for task in tasks}
            ):
                raise RobotAPIException(
                    "Environment API returned mismatched mission task IDs or labels"
                )
            return PreparedMission(
                mission_id=mission.id,
                tasks={
                    label: PreparedTask(by_label[label], asset_names[label])
                    for label in labels
                },
                undock_task_id=by_label[tasks[0]["label"]],
            )
        except Exception:
            logger.exception("Failed to prepare Environment API mission %s", run_label)
            try:
                self.cleanup(run_label)
            except RobotException:
                logger.exception(
                    "Failed to clean up partial mission %s; cleanup will be retried "
                    "before the next mission",
                    run_label,
                )
            raise

    def cleanup(self, label_prefix: str) -> None:
        for resource_type in RESOURCE_TYPES:
            resources = self.environment_api.list_resources(resource_type, label_prefix)
            for resource in resources:
                # The server's label filter is a substring match, not an ownership check.
                if resource.label is not None and resource.label.startswith(
                    label_prefix
                ):
                    self.environment_api.delete_resource(resource_type, resource.id)


def create_pose(position: dict, orientation: dict, *, navigation: bool = False) -> dict:
    if not all(
        math.isfinite(value)
        for value in [
            *(position[axis] for axis in "xyz"),
            *(orientation[axis] for axis in "xyzw"),
        ]
    ):
        raise RobotInfeasibleMissionException(
            "Mission poses must contain finite coordinates"
        )
    pose = {
        "frameId": "map",
        **{f"position{axis.upper()}": position[axis] for axis in "xyz"},
        **{f"orientation{axis.upper()}": orientation[axis] for axis in "xyzw"},
    }
    if navigation:
        pose.update(
            toleranceTranslation=0.0500000007450581,
            toleranceRotation=0.104719758033752,
        )
    return pose


def create_action_payload(poi: dict, label: str) -> dict:
    inspection_type = poi["type"]
    if inspection_type not in INSPECTION_TYPES:
        raise RobotInfeasibleMissionException(
            f"Unsupported inspection type: {inspection_type}"
        )
    config: dict = {"name": f"{label}-target"}
    orientation = {
        "w": 0.737308988858222,
        "x": 0.674585715570665,
        "y": 0.0136916610744799,
        "z": -0.0334978464069242,
    }
    if inspection_type in ("visual", "video", "thermal_video"):
        config.update(
            camera_type="thermal" if inspection_type == "thermal_video" else "normal",
            size={"width": poi["width"], "height": poi["height"]},
        )
        if inspection_type == "visual":
            config["camera_mode"] = "full_auto"
        else:
            duration = poi["recording_duration"]
            if not math.isfinite(duration) or duration <= 0:
                raise RobotInfeasibleMissionException(
                    "Video duration must be finite and positive"
                )
            config.update(record_audio=False, recording_duration=duration)
    elif inspection_type == "thermal":
        config.update(
            min_certainty=0.6,
            normal_operating_range={"min": -20.0, "max": 900.0},
            roi_diameter=5.0,
            temperature_type="Max",
            unit="degreesC",
        )
    else:
        orientation = {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
        config.update(
            autopoint_type="full",
            detection_type=poi["detection_type"],
            frequency_from=poi["frequency_from"],
            frequency_to=poi["frequency_to"],
            roi=poi["roi"],
            snr_value_threshold=poi["snr_value_threshold"],
            frame_id="map",
            operating_conditions="DC",
            electricity_cost=0.0,
            gas_cost=0.0,
            power_ratio=0.0,
            operating_hours_per_year=0.0,
        )
    return {
        "label": f"{label}-action",
        "actionType": INSPECTION_TYPES[inspection_type],
        "config": config,
        "environmentItem": {
            "label": f"{label}-item",
            "pose": create_pose(poi["pos"], orientation),
        },
    }


def closest_waypoint_position(graph: WaypointGraph, position: dict) -> dict:
    point = tuple(position[axis] for axis in "xyz")
    if not all(math.isfinite(value) for value in point):
        raise RobotInfeasibleMissionException("Robot position must be finite")
    nodes = {node.id: node.position for node in graph.nodes}
    nearest = None
    minimum_distance = math.inf
    for edge in graph.edges:
        start, end = nodes[edge.start_pose.id], nodes[edge.end_pose.id]
        direction = tuple(b - a for a, b in zip(start, end))
        length_squared = sum(value * value for value in direction)
        fraction = (
            max(
                0.0,
                min(
                    1.0,
                    sum((p - a) * d for p, a, d in zip(point, start, direction))
                    / length_squared,
                ),
            )
            if length_squared
            else 0.0
        )
        projected = tuple(a + fraction * d for a, d in zip(start, direction))
        distance = math.dist(point, projected)
        if distance < minimum_distance:
            minimum_distance = distance
            nearest = projected
    if nearest is None:
        raise RobotInfeasibleMissionException("No usable waypoint edge was found")
    return dict(zip("xyz", nearest))
