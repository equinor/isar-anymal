import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from alitra import (
    Frame,
    MapAlignment,
    Pose,
    Position,
    Transform,
    align_maps,
)
from requests import Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotInfeasibleMissionException,
    RobotTelemetryNoUpdateException,
    RobotTelemetryPoseException,
    RobotUnknownErrorException,
)
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.status import MissionStatus, RobotStatus, TaskStatus
from robot_interface.models.mission.task import TASKS, TaskTypes
from robot_interface.models.robots.battery_state import BatteryState
from robot_interface.models.robots.media import MediaConfig, MediaConnectionType
from robot_interface.telemetry.payloads import (
    TelemetryBatteryPayload,
    TelemetryPosePayload,
)

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.enums import (
    UserInteractionMode,
    BatteryStatus,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.battery_handler import (
    BatteryHandler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.control_status_handler import (
    ControlStatusHandler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.main_body_state_handler import (
    MainBodyStateHandler,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.pose_handler import (
    PoseHandler,
)

from isar_anymal.robot.api.media_stream import MediaStream
from isar_anymal.robot.api.mission_status_handler import MissionStatusHandler
from isar_anymal.robot.api.request_handler import RequestHandler
from isar_anymal.robot.api.utilities.anybotics_file_handler.anymal_ads_file_transfer import (
    ANYmalADSFileTransfer,
)

from isar_anymal.robot.api.anymal_api.api import ANYmalAPI
from isar_anymal.robot.api.anymal_api.models import ControlMissionResponseDto

logger = logging.getLogger(__name__)


class API:
    def __init__(self) -> None:
        self.request_handler: RequestHandler = RequestHandler()
        self.anymal_api: ANYmalAPI = ANYmalAPI(request_handler=self.request_handler)
        self.pose_handler: PoseHandler = PoseHandler()
        self.battery_handler: BatteryHandler = BatteryHandler()
        self.control_status_handler: ControlStatusHandler = ControlStatusHandler()
        self.mission_status_handler: MissionStatusHandler = MissionStatusHandler()
        self.main_body_state_handler: MainBodyStateHandler = MainBodyStateHandler()

        map_alignment: MapAlignment = MapAlignment.from_config(
            Path(
                os.path.dirname(os.path.realpath(__file__)),
                f"../../config/maps/{settings.MAP_NAME}.json",
            )
        )
        self.transform: Transform = align_maps(
            map_alignment.map_from, map_alignment.map_to, rot_axes="z"
        )

        self.media_stream: Optional[MediaStream] = None
        self.file_transfer_handler: ANYmalADSFileTransfer = ANYmalADSFileTransfer(
            mission_creation=True
        )

    def take_control(self) -> str:
        lease_id: str = self.anymal_api.request_control_authority_lease()
        logger.info(
            f"Successfully taken control of {settings.ROBOT_NAME} with lease_id: {lease_id}"
        )
        return lease_id

    def release_control(self, lease_id: str) -> None:
        self.anymal_api.release_control_authority_lease(lease_id=lease_id)
        logger.info(f"Successfully released control of {settings.ROBOT_NAME}")

    def disengage_protective_stop(self) -> None:
        lease_id: str = self.take_control()
        try:
            self.anymal_api.disengage_protective_stop(lease_id=lease_id)
        finally:
            self.release_control(lease_id=lease_id)

    def prepare_mission_plan(
        self, mission: Mission
    ) -> Tuple[Optional[str], Optional[list]]:
        """Prepare a mission plan and adjust the environment file on the robot
        to be capable of running the given mission."""
        inspections: List[Dict] = self.convert_tasks_to_anymal_inspections(
            tasks=mission.tasks
        )

        try:
            mission_id: Optional[str]
            mission_tasks: Optional[list]
            mission_id, mission_tasks = (
                self.file_transfer_handler.create_ad_hoc_inspections(
                    inspections=inspections
                )
            )
            time.sleep(settings.ENVIRONMENT_FILE_SYNC_DELAY)
            return mission_id, mission_tasks
        except Exception as e:
            logger.exception(e)
            error_description: str = "Failed to prepare mission plan"
            logger.exception(error_description)
            raise RobotUnknownErrorException(error_description)

    def convert_tasks_to_anymal_inspections(self, tasks: List[TASKS]) -> List[Dict]:
        inspections: List[Dict] = []
        task_counter: int = 0
        for task in tasks:
            task_type: str = self.extract_task_type(task)

            robot_pose_transformed: Pose = self.transform.transform_pose(
                task.robot_pose, from_=task.robot_pose.frame, to_=Frame("robot")
            )

            target_position_transformed: Position
            if task.type == TaskTypes.TakeCO2Measurement:
                # For CO2 measurements, we use the robot pose as the target position
                target_position_transformed = robot_pose_transformed.position
            else:
                target_position_transformed = self.transform.transform_position(
                    task.target, from_=task.target.frame, to_=Frame("robot")
                )

            inspections.append(
                self.create_inspection(
                    pose=robot_pose_transformed,
                    target_position=target_position_transformed,
                    task=task,
                    task_type=task_type,
                )
            )
            task_counter += 1

        return inspections

    @staticmethod
    def create_inspection(
        pose: Pose,
        target_position: Position,
        task: TASKS,
        task_type: str,
    ) -> Dict:
        return {
            "poi": {
                "pos": {
                    "x": target_position.x,
                    "y": target_position.y,
                    "z": target_position.z,
                },
                "width": task.zoom.objectWidth if task.zoom else 10,
                "height": task.zoom.objectHeight if task.zoom else 10,
                "type": task_type,
                "name": task.id,
                "detection_type": (
                    task.detection_type.value
                    if hasattr(task, "detection_type")
                    else None
                ),
                "frequency_from": getattr(task, "frequency_from", None),
                "frequency_to": getattr(task, "frequency_to", None),
                "snr_value_threshold": getattr(task, "snr_value_threshold", None),
            },
            "poo": {
                "pos": {
                    "x": pose.position.x,
                    "y": pose.position.y,
                    "z": pose.position.z,
                },
                "orientation": {
                    "x": float(pose.orientation.x),
                    "y": float(pose.orientation.y),
                    "z": float(pose.orientation.z),
                    "w": float(pose.orientation.w),
                },
            },
        }

    @staticmethod
    def extract_task_type(task) -> str:
        task_type: str
        if task.type == TaskTypes.TakeImage:
            task_type = "visual"
        elif task.type == TaskTypes.TakeThermalImage:
            task_type = "thermal"
        elif task.type == TaskTypes.TakeCO2Measurement:
            task_type = "co2"
        elif task.type == TaskTypes.TakeAcousticMeasurement:
            task_type = "acoustic"
        else:
            error_description = f"Unsupported task type: {task.type}"
            logger.error(error_description)
            raise RobotInfeasibleMissionException(error_description)

        return task_type

    def start_mission(self, mission_id: str) -> str:
        lease_id: str = self.take_control()

        logger.info("Attempting to start mission")
        try:
            self.anymal_api.set_user_interaction_mode(
                user_interaction_mode=UserInteractionMode.UIM_AUTONOMOUS,
                lease_id=lease_id,
            )

            response: ControlMissionResponseDto = (
                self.anymal_api.start_predefined_mission(
                    mission_id=mission_id,
                    lease_id=lease_id,
                )
            )
        finally:
            self.release_control(lease_id=lease_id)

        logger.info(
            f"Mission {mission_id} started successfully with run UID {response.run_uid}"
        )
        return response.run_uid

    def start_dock_mission(self) -> str:
        lease_id: str = self.take_control()

        try:
            self.anymal_api.set_user_interaction_mode(
                user_interaction_mode=UserInteractionMode.UIM_AUTONOMOUS,
                lease_id=lease_id,
            )

            response: ControlMissionResponseDto = (
                self.anymal_api.start_predefined_mission(
                    mission_id=settings.DOCK_MISSION_NAME,
                    lease_id=lease_id,
                )
            )
        finally:
            self.release_control(lease_id=lease_id)

        logger.info(f"Mission {settings.DOCK_MISSION_NAME} started successfully")
        return response.run_uid

    def pause_mission(self, mission_run_uid: Optional[str]) -> None:
        lease_id: str = self.take_control()
        try:
            _ = self.anymal_api.pause_mission(
                mission_run_uid=mission_run_uid if mission_run_uid is not None else "",
                lease_id=lease_id,
            )
        finally:
            self.release_control(lease_id=lease_id)

    def resume_mission(self, mission_run_uid: str) -> None:
        lease_id: str = self.take_control()
        try:
            _ = self.anymal_api.resume_mission(
                mission_run_uid=mission_run_uid if mission_run_uid is not None else "",
                lease_id=lease_id,
            )
        finally:
            self.release_control(lease_id=lease_id)

    def get_task_status(self, task_id: str) -> TaskStatus:
        return self.mission_status_handler.get_task_status(task_id=task_id)

    def get_mission_status(self) -> MissionStatus:
        return self.mission_status_handler.get_mission_status()

    def generate_media_config(self) -> MediaConfig:
        if self.media_stream is None or not self.media_stream.is_active():
            self.media_stream = MediaStream(request_handler=self.request_handler)
            self.media_stream.activate_stream()

        livestream_url: str
        livestream_token: str
        livestream_url, livestream_token = self.media_stream.get_liveview_info()

        return MediaConfig(
            url=livestream_url,
            token=livestream_token,
            media_connection_type=MediaConnectionType.LiveKit,
        )

    def get_robot_status(self) -> RobotStatus:
        if not self.robot_is_online():
            return RobotStatus.Offline

        if not settings.AUTO_DISABLE_PROTECTIVE_STOP:
            if self.control_status_handler.control_status.protective_stop_engaged:
                return RobotStatus.BlockedProtectiveStop
            else:
                logger.warning(
                    "Received a robot status call before receiving a protective stop event, will not evaluate protective stop status"
                )

        try:
            if self.robot_is_home():
                return RobotStatus.Home
        except Exception:
            logger.warning(
                "Could not determine if robot is home, will default to available"
            )
            pass

        return RobotStatus.Available

    def robot_is_online(self) -> bool:
        connection_response: Response = self.request_handler.get(
            url=f"{settings.SERVER_URL}/anymal-api/connection/"
        )
        for connection_info in connection_response.json():
            if not connection_info["anymalName"] == settings.ROBOT_NAME:
                continue

            return connection_info["connectionStatus"] == "CS_CONNECTED"

        logger.error(f"Could not find robot {settings.ROBOT_NAME} in connection list")
        return False

    def robot_is_home(self) -> bool:
        if self.battery_handler.battery.state is None:
            raise RobotTelemetryNoUpdateException("Could not get battery state")

        if self.battery_handler.battery.level is None:
            raise RobotTelemetryNoUpdateException("Could not get battery level")

        if self.battery_handler.battery.state is BatteryState.Charging:
            return True

        if self.battery_handler.battery.level >= settings.BATTERY_FULL_VALUE:
            return True

        return False

    def get_pose_telemetry_payload(self, isar_id: str, robot_name: str) -> str:
        retry_count: int = 0
        while retry_count < settings.MAX_TELEMETRY_RETRIES:
            try:
                pose: Pose = self.get_robot_pose()
                break
            except RobotTelemetryPoseException:
                retry_count += 1
                time.sleep(settings.TELEMETRY_RETRY_INTERVAL)
        else:
            raise RobotTelemetryPoseException("Could not get pose")

        pose_payload: TelemetryPosePayload = TelemetryPosePayload(
            isar_id=isar_id,
            robot_name=robot_name,
            timestamp=datetime.now(timezone.utc),
            pose=pose,
        )

        return pose_payload.model_dump_json()

    def get_battery_telemetry_payload(self, isar_id: str, robot_name: str) -> str:
        battery_payload: TelemetryBatteryPayload = TelemetryBatteryPayload(
            isar_id=isar_id,
            robot_name=robot_name,
            timestamp=datetime.now(timezone.utc),
            battery_level=self.get_battery_level(),
            battery_state=self.get_battery_state(),
        )

        return battery_payload.model_dump_json()

    def get_robot_pose(self) -> Pose:
        if self.pose_handler.pose is None:
            raise RobotTelemetryPoseException("Could not get pose")
        return self.pose_handler.pose

    def get_battery_level(self) -> float:
        if self.battery_handler.battery.level is None:
            raise RobotTelemetryNoUpdateException("Could not get battery level")
        return self.battery_handler.battery.level

    def get_battery_state(self) -> BatteryState:
        if self.battery_handler.battery.state is None:
            raise RobotTelemetryNoUpdateException("Could not get battery state")
        return self.battery_handler.battery.state

    def get_battery_status(self) -> BatteryStatus:
        if self.battery_handler.anymal_reported_battery_status is None:
            raise RobotTelemetryNoUpdateException("Could not get battery status")
        return self.battery_handler.anymal_reported_battery_status

    def get_relative_humidity(self) -> float:
        if self.main_body_state_handler.relative_humidity is None:
            raise RobotTelemetryNoUpdateException("Could not get relative humidity")
        return self.main_body_state_handler.relative_humidity

    def get_differential_pressure(self) -> float:
        if self.main_body_state_handler.differential_pressure is None:
            raise RobotTelemetryNoUpdateException("Could not get differential pressure")
        return self.main_body_state_handler.differential_pressure

    def get_temperature(self) -> float:
        if self.main_body_state_handler.temperature is None:
            raise RobotTelemetryNoUpdateException("Could not get temperature")
        return self.main_body_state_handler.temperature
