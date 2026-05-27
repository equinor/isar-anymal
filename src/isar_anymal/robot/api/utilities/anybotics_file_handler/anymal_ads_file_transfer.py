import copy
import json
import logging
import math
import re
import time
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy
import yaml
from robot_interface.models.exceptions.robot_exceptions import (
    RobotUnknownErrorException,
)

from isar_anymal.config.settings import settings
from isar_anymal.robot.api.ads_api.api import (
    send_file_through_ads_api,
    get_file_through_ads_api,
)
from isar_anymal.robot.api.utilities.anybotics_file_handler.environment_utils import (
    acoustic_inspection,
    nav_goal,
    nav_zone,
    relation,
    thermal_inspection,
    visual_inspection,
)
from isar_anymal.robot.api.utilities.anybotics_file_handler.mission_utils import (
    co2_measurement_task,
    dock_task,
    inspection_task,
    mission_template,
    set_last_task_transitions,
    set_next_task_name,
    simple_inspection_task,
    undock_task,
)
from isar_anymal.robot.api.utilities.anybotics_file_handler.yaml_dumper import (
    AnyboticsYamlDumper,
)

logger = logging.getLogger(__name__)


class ANYmalADSFileTransfer:
    def __init__(
        self,
        mission_name="AdHocMission",
        transform=None,
        left_handed_coordinate=False,
        mission_creation=False,
        distant_user="integration",
    ) -> None:
        self.environment_name = settings.ENVIRONMENT_NAME

        self.environment_file_name = settings.ENVIRONMENT_FILE_NAME
        self.mission_name = mission_name
        self.working_folder: str = settings.ENVIRONMENT_FILE_WORKING_FOLDER
        self.environment_cleaned: dict = {"object_relations": [], "objects": []}
        self.mission_creation = mission_creation
        self.distant_user = distant_user
        self.file_retrieval_num_retries = settings.FILE_RETRIEVAL_NUM_RETRIES
        self.file_retrieval_retry_interval = settings.FILE_RETRIEVAL_RETRY_INTERVAL

        if transform and transform.any():
            self.set_transform(transform)
        else:
            self.set_unit_transform()
        self.left_handed_coordinate = left_handed_coordinate

        self.adhoc_mission_filepath = False

    def create_ad_hoc_inspections(self, inspections: List[Dict]):
        # Fetch environment from robot
        environment_filepath: Path = self.get_environment_file_with_retry()
        # Fetch waypoints from robot
        waypoint_filepath: Path = self.get_waypoint_file_with_retry()

        # TODO put a try catch pattern
        if environment_filepath:
            # Remove old ad-hoc inspections
            bck_environment_filepath: Path = self.cleanup_environment(
                environment_filepath
            )
            # Add the new ad-hoc inspection

            adhoc_environment_filepath, poi_task = self.add_new_poi(
                inspections=inspections, waypoint_filepath=waypoint_filepath
            )
            if poi_task is None:
                logger.warning("Poi task is none")

            if self.mission_creation:
                # Generate a mission containing the new poi
                self.adhoc_mission_filepath = self.create_adhoc_mission(
                    self.mission_name, poi_task
                )

            # Transfer environment & mission to robot
            # Set prune to true to enforce automatic reloading of environment
            success = True
            success = success and self.send_environment_file(
                bck_environment_filepath, True
            )  # This will delete the environment file and prepare for a forced reload on the robot
            if not success:
                logger.warning(
                    "Failed after trying to send the bck environment filepath"
                )

            success = success and self.send_environment_file(
                adhoc_environment_filepath, True
            )  # This will new file and delete the temporary file
            if not success:
                logger.warning("Failed after trying to send the environment filepath")

            if self.mission_creation:
                success = success and self.send_mission_file(
                    self.adhoc_mission_filepath
                )
                if not success:
                    logger.warning("Failed after trying to send the mission file")
        else:
            success = False

        # Return the ad-hoc mission if all actions were successful
        if success:
            return self.mission_name, poi_task
        else:
            return None, None

    def cleanup_environment(self, environment_filepath: Path) -> Path:
        self.environment_cleaned = {"object_relations": [], "objects": []}
        # Load the environment
        with open(environment_filepath, "r") as environment_file:
            environment = yaml.load(environment_file, Loader=yaml.FullLoader)
        # Check for ad-hoc items and delete them
        adhoc_name_pattern = "^AdHoc-.*$"
        for item in environment["objects"]:
            if re.match(adhoc_name_pattern, item["label"]):
                # print("Deleting: ", item["label"])
                continue
            else:
                self.environment_cleaned["objects"].append(item)

        for item in environment["object_relations"]:
            if re.match(adhoc_name_pattern, item["parent"]):
                # print("Deleting: ", item["parent"])
                continue
            else:
                self.environment_cleaned["object_relations"].append(item)

        bck_environment_filepath = Path(str(environment_filepath) + ".bck")

        with open(bck_environment_filepath, "w") as bck_environment_file:
            bck_environment_file.write(
                yaml.dump(
                    self.environment_cleaned,
                    Dumper=AnyboticsYamlDumper,
                    sort_keys=False,
                )
            )

        return bck_environment_filepath

    def add_new_poi(
        self, inspections: List[Dict], waypoint_filepath: Path
    ) -> Tuple[str, List[Dict]]:

        adhoc_environment: Dict = copy.deepcopy(self.environment_cleaned)
        mission_tasks: List[Dict] = []

        for idx, inspection in enumerate(inspections):
            poi = inspection["poi"]
            poo = inspection["poo"]

            # Coordinate transformation (assuming left handed handed system)
            poi = self.transform_anymal_cs(poi)
            poo = self.transform_anymal_cs(poo)

            poi_name = poi["name"]

            position_on_wp, orientations = self.compute_nav_goal_on_waypoints(
                waypoint_filepath, poo, poi
            )

            zone_names = []

            co2_nav_goal: dict

            for idx_orientation, orientation in enumerate(orientations):
                this_nav_goal = copy.deepcopy(nav_goal)
                this_nav_zone = copy.deepcopy(nav_zone)

                this_nav_goal["name"] = (
                    f"AdHoc-{idx}-{poi_name}-{idx_orientation}_NavGoal"
                )
                if poi["type"] == "co2":
                    co2_nav_goal = this_nav_goal["name"]

                this_nav_zone["name"] = (
                    f"AdHoc-{idx}-{poi_name}-{idx_orientation}_NavZone"
                )
                this_nav_goal["label"] = this_nav_goal["name"]
                this_nav_zone["label"] = this_nav_zone["name"]

                this_nav_goal["pose"]["pose"]["orientation"] = copy.deepcopy(
                    orientation
                )
                this_nav_goal["pose"]["pose"]["position"] = copy.deepcopy(
                    position_on_wp
                )

                adhoc_environment["objects"].append(this_nav_goal)
                adhoc_environment["objects"].append(this_nav_zone)

                goal_to_zone = copy.deepcopy(relation)
                goal_to_zone["child"] = this_nav_goal["name"]
                goal_to_zone["parent"] = this_nav_zone["name"]

                adhoc_environment["object_relations"].append(goal_to_zone)

                zone_names.append(this_nav_zone["name"])

            item_data = {
                "thermal": {"suffix": "VIT", "type_data": thermal_inspection},
                "visual": {"suffix": "VIS", "type_data": visual_inspection},
                "co2": {"suffix": "CO2", "type_data": visual_inspection},
                "acoustic": {"suffix": "ACO", "type_data": acoustic_inspection},
            }

            poi_suffix = item_data[poi["type"]]["suffix"]

            this_inspection = copy.deepcopy(item_data[poi["type"]]["type_data"])
            this_inspection["pose"]["pose"]["position"] = poi["pos"]
            if poi["type"] == "co2":
                this_inspection["name"] = co2_nav_goal
            else:
                this_inspection["name"] = f"AdHoc-{idx}-{poi_name}-{poi_suffix}"
            this_inspection["label"] = f"AdHoc-{idx}-{poi_name}"

            mission_tasks.append(
                {
                    "name": this_inspection["name"],
                    "type": poi["type"],
                    "label": poi_name,
                }
            )

            if poi["type"] == "visual" and "width" in poi:
                this_inspection["size"]["width"] = poi["width"]

            if poi["type"] == "visual" and "height" in poi:
                this_inspection["size"]["height"] = poi["height"]

            if poi["type"] == "acoustic":
                this_inspection["detection_type"] = poi["detection_type"]
                this_inspection["frequency_from"] = poi["frequency_from"]
                this_inspection["frequency_to"] = poi["frequency_to"]
                this_inspection["snr_value_threshold"] = poi["snr_value_threshold"]

            adhoc_environment["objects"].append(this_inspection)

            for zone_name in zone_names:
                inspection_to_zone = copy.deepcopy(relation)
                inspection_to_zone["child"] = zone_name
                inspection_to_zone["parent"] = this_inspection["name"]
                adhoc_environment["object_relations"].append(inspection_to_zone)

        adhoc_environment_filepath = self.working_folder + self.environment_file_name

        with open(adhoc_environment_filepath, "w") as adhoc_environment_file:
            adhoc_environment_file.write(
                yaml.dump(
                    adhoc_environment, Dumper=AnyboticsYamlDumper, sort_keys=False
                )
            )

        return adhoc_environment_filepath, mission_tasks

    def create_adhoc_mission(self, mission_name, task_list):
        task_list.insert(
            0, {"name": "adhoc-undock", "type": "undock", "label": "undock"}
        )

        mission_tasks = []
        previous_task = None
        initial_task = None

        ### For each item in the list create a full mission task
        for task in task_list:
            mission_task = self.create_task_entry(task)

            # Skip if we can not create that entry
            if mission_task is None:
                continue

            # Set as next task in previous task
            if previous_task is not None:
                set_next_task_name(previous_task, mission_task["name"])
            else:
                initial_task = mission_task["name"]

            # Add task to the mission
            mission_tasks.append(mission_task)
            previous_task = mission_task

        if previous_task is not None:
            set_last_task_transitions(previous_task)

        ### Update global mission settings
        for mission_setting in mission_template["settings"]:
            if mission_setting["name"] == "default_initial_state":
                mission_setting["value"] = initial_task
            elif mission_setting["name"] == "states":
                mission_setting["value"] = mission_tasks

        mission_template["name"] = mission_name

        adhoc_mission_filepath = self.working_folder + mission_name + ".yaml"

        ### Generate the mission file
        with open(adhoc_mission_filepath, "w") as file:
            file.write(
                yaml.dump(
                    mission_template,
                    Dumper=AnyboticsYamlDumper,
                    default_flow_style=False,
                )
            )

        return adhoc_mission_filepath

    def create_task_entry(self, task):

        task_data = {
            "thermal": {
                "task_prefix": "Inspect",
                "item_suffix": "VIT",
                "plugin": "visual_inspection_thermal_behavior_plugins",
                "action": "Inspect",
                "mission_task": inspection_task,
            },
            "visual": {
                "task_prefix": "Inspect",
                "item_suffix": "VIS",
                "plugin": "visual_inspection_simple_behavior_plugins",
                "action": "Inspect",
                "mission_task": simple_inspection_task,
            },
            "co2": {
                "task_prefix": "InspectAreaFromPose",
                "plugin": "gas_inspection_behavior_plugins",
                "action": "InspectAreaFromPose",
                "mission_task": co2_measurement_task,
            },
            "acoustic": {
                "task_prefix": "Inspect",
                "item_suffix": "ACO",
                "plugin": "acoustic_imaging_behavior_plugins",
                "action": "Inspect",
                "mission_task": inspection_task,
            },
            "dock": {
                "task_prefix": "",
                "item_suffix": "",
                "plugin": "system_behavior_plugins",
                "mission_task": dock_task,
            },
            "undock": {
                "task_prefix": "",
                "item_suffix": "",
                "plugin": "system_behavior_plugins",
                "mission_task": undock_task,
            },
        }

        if task["type"] in task_data:
            active_task_type = task_data[task["type"]]
            mission_task = copy.deepcopy(active_task_type["mission_task"])
        else:
            return

        # Add prefix and Suffix
        if active_task_type["task_prefix"]:
            mission_task["name"] = task["label"]
        else:
            mission_task["name"] = task["label"]

        # Configure task parameters
        if (
            len(mission_task["settings"]) > 0
            and mission_task["settings"][0]["name"] != "duration"
        ):
            mission_task["settings"][0]["value"] = task["name"]

        # Configure task behavior plugin
        mission_task["type"] = mission_task["type"].replace(
            "[plugin_name]", active_task_type["plugin"]
        )
        if "[plugin_action]" in mission_task["type"]:
            mission_task["type"] = mission_task["type"].replace(
                "[plugin_action]", active_task_type["action"]
            )

        return mission_task

    def get_environment_file_with_retry(self) -> Path:
        retries: int = 0

        while True:
            try:
                retries += 1
                logger.info("Getting environment file")
                environment_file: Path = self.get_environment_file()
                return environment_file
            except Exception:
                if retries < self.file_retrieval_num_retries:
                    logger.warning("Could not get environment file, will retry...")
                    time.sleep(self.file_retrieval_retry_interval)
                    continue
                else:
                    logger.exception(
                        f"Could not get environment file after {self.file_retrieval_num_retries}. Aborting... "
                    )
                    error_description: str = "Could not get environment_file"
                    raise RobotUnknownErrorException(error_description)

        raise RobotUnknownErrorException(
            "Exited while loop without retrieving environment file"
        )

    def get_environment_file(self) -> Path:
        file_path_on_robot: str = (
            f"/home/{self.distant_user}/ANYmal/Environments/{self.environment_name}/environments/environment.yaml"
        )
        local_path: Path = get_file_through_ads_api(
            computer="npc",
            robot_name=settings.ROBOT_NAME,
            file_path_on_robot=file_path_on_robot,
            output_dir=Path(self.working_folder),
        )
        return local_path

    def get_waypoint_file_with_retry(self) -> Path:
        retries: int = 0

        while True:
            try:
                retries += 1
                logger.info("Getting waypoint file")
                waypoint_file: Path = self.get_waypoint_file()
                return waypoint_file
            except Exception:
                if retries < self.file_retrieval_num_retries:
                    logger.warning("Could not get waypoint file, will retry...")
                    time.sleep(self.file_retrieval_retry_interval)
                    continue
                else:
                    logger.exception(
                        f"Could not get waypoint file after {self.file_retrieval_num_retries}. Aborting... "
                    )
                    error_description: str = "Could not get waypoint file"
                    raise RobotUnknownErrorException(error_description)
        raise RobotUnknownErrorException(
            "Exited while loop without retrieving waypoint file"
        )

    def get_waypoint_file(self) -> Path:
        file_path_on_robot: str = (
            f"/home/{self.distant_user}/ANYmal/Environments/{self.environment_name}/waypoints/waypoints.json"
        )
        local_path: Path = get_file_through_ads_api(
            computer="npc",
            robot_name=settings.ROBOT_NAME,
            file_path_on_robot=file_path_on_robot,
            output_dir=Path(self.working_folder),
        )
        return local_path

    def send_environment_file(self, environment_filepath, prune=False):
        send_file_through_ads_api(
            computer="npc",
            destination_path=f"/home/{self.distant_user}/ANYmal/Environments/{self.environment_name}/environments/",
            robot_name=settings.ROBOT_NAME,
            file_path=environment_filepath,
            prune=prune,
        )
        return True

    def send_mission_file(self, mission_filepath, prune=False):
        send_file_through_ads_api(
            computer="npc",
            destination_path=f"/home/{self.distant_user}/ANYmal/Environments/{self.environment_name}/missions/",
            robot_name=settings.ROBOT_NAME,
            file_path=mission_filepath,
            prune=False,  # Pruning on mission file will delete the necessary Dock mission
        )
        return True

    @staticmethod
    def run_subprocess(command: str) -> Optional[str]:
        try:
            result: subprocess.CompletedProcess = subprocess.run(
                command, shell=True, text=True, capture_output=True, check=True
            )
            output: str = result.stdout
            return output
        except subprocess.CalledProcessError:
            logger.exception(f"Error executing command: ´{command}´")
            return None

    def compute_nav_goal_on_waypoints(
        self, waypoint_filepath: Path, robot_pose: Dict, target_position: Dict
    ):
        with open(waypoint_filepath, "r") as waypoint_file:
            waypoints: Dict = json.load(waypoint_file)

        closest_position, closest_edge_nodes = self.find_closest_position_and_nodes(
            robot_pose=robot_pose, waypoints=waypoints
        )
        closest_edge_nodes = (
            self.adjust_height_coordinate_according_to_distance_to_edge(
                closest_edge_nodes=closest_edge_nodes, closest_position=closest_position
            )
        )

        orientations: List[Dict] = [robot_pose["orientation"]]

        closest_position["x"] = float(closest_position["x"])
        closest_position["y"] = float(closest_position["y"])
        closest_position["z"] = float(closest_position["z"])

        return closest_position, orientations

    @staticmethod
    def adjust_height_coordinate_according_to_distance_to_edge(
        closest_edge_nodes: List[Dict], closest_position: Dict
    ) -> List[Dict]:
        # Compute height proportionally according to distance to each side of the edge
        if closest_edge_nodes[1]["x"] != closest_edge_nodes[0]["x"]:
            closest_position["z"] = closest_edge_nodes[0]["z"] + (
                (closest_edge_nodes[1]["z"] - closest_edge_nodes[0]["z"])
                * (closest_position["x"] - closest_edge_nodes[0]["x"])
                / (closest_edge_nodes[1]["x"] - closest_edge_nodes[0]["x"])
            )
        elif closest_edge_nodes[1]["y"] != closest_edge_nodes[0]["y"]:
            closest_position["z"] = closest_edge_nodes[0]["z"] + (
                (closest_edge_nodes[1]["z"] - closest_edge_nodes[0]["z"])
                * (closest_position["y"] - closest_edge_nodes[0]["y"])
                / (closest_edge_nodes[1]["y"] - closest_edge_nodes[0]["y"])
            )
        else:
            closest_position["z"] = (
                closest_edge_nodes[0]["z"] + closest_edge_nodes[1]["z"]
            ) / 2

        return closest_edge_nodes

    def find_closest_position_and_nodes(
        self, robot_pose: Dict, waypoints: Dict
    ) -> Tuple[Optional[Dict], Optional[List]]:
        # Find the closest edge from the PoO
        min_dist: float = 0
        closest_edge_nodes: Optional[List] = None
        closest_position: Optional[Dict] = None
        for edge in waypoints["edges"]:
            edge_nodes: List[Dict] = [
                self.find_waypoint_node(waypoints["nodes"], edge["start_node_id"]),
                self.find_waypoint_node(waypoints["nodes"], edge["end_node_id"]),
            ]
            pos, dist = self.compute_distance_to_edge(edge_nodes, robot_pose["pos"])

            if closest_edge_nodes is None or dist < min_dist:
                min_dist = dist
                closest_edge_nodes = edge_nodes
                closest_position = pos

        return closest_position, closest_edge_nodes

    @staticmethod
    def find_waypoint_node(nodes, node_id: str) -> Dict:
        for node in nodes:
            if node["id"] == node_id:
                return {
                    "x": node["pose_stamped"]["position"][0],
                    "y": node["pose_stamped"]["position"][1],
                    "z": node["pose_stamped"]["position"][2],
                    "orientation": node["pose_stamped"]["orientation"],
                    "tolerance": node["pose_stamped"]["tolerance"],
                }

        error_description: str = f"Node id {node_id} not found in waypoint nodes"
        logger.error(error_description)
        raise RobotUnknownErrorException(error_description)

    @staticmethod
    def compute_distance_to_edge(edge: List[Dict], point: Dict) -> Tuple[Dict, float]:
        # Differences between point and edge[0]
        A = point["x"] - edge[0]["x"]
        B = point["y"] - edge[0]["y"]
        E = point["z"] - edge[0]["z"]

        # Differences between edge[1] and edge[0]
        C = edge[1]["x"] - edge[0]["x"]
        D = edge[1]["y"] - edge[0]["y"]
        F = edge[1]["z"] - edge[0]["z"]

        # Dot product and squared length of the edge
        dot = A * C + B * D + E * F
        len_sq = C * C + D * D + F * F
        param = -1
        if len_sq != 0:
            param = dot / len_sq

        # Calculate the closest point on the edge
        if param < 0:
            xx = edge[0]["x"]
            yy = edge[0]["y"]
            zz = edge[0]["z"]
        elif param > 1:
            xx = edge[1]["x"]
            yy = edge[1]["y"]
            zz = edge[1]["z"]
        else:
            xx = edge[0]["x"] + param * C
            yy = edge[0]["y"] + param * D
            zz = edge[0]["z"] + param * F

        # Compute the distance between the point and the closest point on the edge
        dx = point["x"] - xx
        dy = point["y"] - yy
        dz = point["z"] - zz
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)

        return {"x": xx, "y": yy, "z": zz}, distance

    def transform_left_to_right_handed_cs(self, point):
        l_vec = point["pos"]
        r_M_l = numpy.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]])
        r_vec = numpy.dot(r_M_l, [l_vec["x"], l_vec["y"], l_vec["z"]])
        point["pos"] = {
            "x": r_vec[0].item(),
            "y": r_vec[1].item(),
            "z": r_vec[2].item(),
        }
        return point

    def transform_anymal_cs(self, point):
        # Switch coordinate system first
        if self.left_handed_coordinate:
            point = self.transform_left_to_right_handed_cs(point)
        # Apply transform
        vec = point["pos"]
        anymal_vec = numpy.dot(self.anymal_M, [vec["x"], vec["y"], vec["z"], 1])
        point["pos"] = {
            "x": anymal_vec[0].item(),
            "y": anymal_vec[1].item(),
            "z": anymal_vec[2].item(),
        }
        return point

    def set_unit_transform(self):
        self.anymal_M = numpy.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        )

    def set_transform(self, transform):
        self.anymal_M = transform
