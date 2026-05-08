import logging

from queue import Queue
from threading import Thread
from typing import Callable, List, Optional

from robot_interface.models.exceptions.robot_exceptions import (
    RobotInfeasibleMissionException,
    RobotMissionStatusException,
    RobotTaskStatusException,
    RobotUnknownErrorException,
)
from robot_interface.models.inspection.inspection import Inspection
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.status import MissionStatus, RobotStatus, TaskStatus
from robot_interface.models.mission.task import InspectionTask
from robot_interface.models.robots.media import MediaConfig
from robot_interface.robot_interface import RobotInterface
from robot_interface.telemetry.mqtt_client import MqttTelemetryPublisher

from isar_anymal.config import settings
from isar_anymal.open_telemetry.metrics_handler import MetricsHandler
from isar_anymal.robot.api import API
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.inspection_handler import (
    InspectionHandler,
)
from isar_anymal.robot.api.utilities.mission import is_return_to_home_mission

logger = logging.getLogger(__name__)


class Robot(RobotInterface):
    def __init__(self, robot_name: str, isar_id: str) -> None:
        super().__init__(robot_name=robot_name, isar_id=isar_id)

        self.anymal: API = API()
        self.inspection_handler: InspectionHandler = InspectionHandler()
        self.metrics_handler: MetricsHandler = MetricsHandler(
            anymal_api=self.anymal, robot_name=robot_name, isar_id=isar_id
        )

        self.current_anymal_mission_id: Optional[str] = None
        self.current_isar_mission_id: Optional[str] = None
        self.return_to_home_mission_running: bool = False

        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def initiate_mission(self, mission: Mission) -> None:
        """Start a new ISAR mission on the ANYmal robot.

        This method is the entry-point used by ISAR to kick off robot execution.
        It resets the internal "currently running mission" bookkeeping, decides
        whether the request is a special *return-to-home/docking* mission, and
        otherwise converts the ISAR mission into an ANYmal mission plan and
        starts it on the robot.

        Args:
            mission: The ISAR mission to execute.

        Raises:
            RobotInfeasibleMissionException:
                The mission plan is not feasible for execution on the ANYmal robot.
            RobotAPIException:
                If the underlying robot API returns an error.
            RobotCommunicationException:
                If communication with the ANYmal REST API fails (transport/
                connectivity errors).
            RobotUnknownErrorException:
                For unexpected failures.
        """
        logger.info(f"Received request to initiate mission with ID {mission.id}")

        self.current_anymal_mission_id = None
        self.current_isar_mission_id = None
        self.anymal.mission_status_handler.last_mission_event = None
        if is_return_to_home_mission(mission=mission):
            self.current_anymal_mission_id = self.anymal.start_dock_mission()
            self.current_isar_mission_id = mission.id
            self.return_to_home_mission_running = True
            return

        self.return_to_home_mission_running = False
        mission_id: Optional[str]
        anymal_mission_tasks: Optional[list]
        mission_id, anymal_mission_tasks = self.anymal.prepare_mission_plan(
            mission=mission
        )
        if mission_id is None or anymal_mission_tasks is None:
            error_message: str = "Failed to prepare mission plan."
            logger.error(error_message)
            raise RobotInfeasibleMissionException(error_message)

        if settings.AUTO_DISABLE_PROTECTIVE_STOP:
            self.anymal.disengage_protective_stop()

        self.current_anymal_mission_id = self.anymal.start_mission(
            mission_id=mission_id
        )
        self.current_isar_mission_id = mission.id

        self.inspection_handler.missions_inspection_queue.append(
            (self.current_anymal_mission_id, mission)
        )
        for task in mission.tasks:
            anymal_point_of_interest_name: list[str] = [
                anymal_task["name"]
                for anymal_task in anymal_mission_tasks
                if anymal_task["label"] == task.id
            ]
            if len(anymal_point_of_interest_name) != 1:
                logger.error(
                    f"Failed to find task name for task {task.id}. Will not upload data for this task."
                )
                continue
            self.inspection_handler.inspections_queue.append(
                (task, anymal_point_of_interest_name[0])
            )

    def task_status(self, task_id: str) -> TaskStatus:
        if self.anymal.mission_status_handler.last_mission_event is None:
            return TaskStatus.NotStarted
        if (
            self.anymal.mission_status_handler.last_mission_event.metadata.mission_run_id
            != self.current_anymal_mission_id
        ):
            raise RobotTaskStatusException(
                "Tried to read the status for a task that was not the current mission id"
            )

        if self.return_to_home_mission_running:
            task_id = settings.DOCK_TASK_ID

        task_status: TaskStatus
        task_status = self.anymal.get_task_status(task_id=task_id)

        if not (
            task_status is TaskStatus.NotStarted or task_status is TaskStatus.InProgress
        ):
            self.return_to_home_mission_running = False

        return task_status

    def mission_status(self, mission_id: str) -> MissionStatus:
        if self.current_isar_mission_id != mission_id:
            error_description: str = (
                f"Attempted to read mission status for mission with ID: {mission_id} but found that a different mission "
                f"with ID: {self.current_isar_mission_id} was running"
            )
            logger.error(error_description)
            raise RobotMissionStatusException(error_description)

        # In this case we assume that the mission_id is for the current mission
        return self.anymal.get_mission_status()

    def stop(self) -> None:
        """Stop the currently running mission on the robot.

        This method forwards the stop request to the underlying ANYmal API for
        the mission identified by ``self.current_anymal_mission_id``. Note that the functionality
        to stop the robot is the same as pausing.

        Raises:
            RobotNoMissionRunningException: If there is no active mission on the robot.
            RobotAPIException: If the underlying robot API returns an error.
            RobotCommunicationException: If the stop request fails due to
                connectivity/transport issues.
            RobotUnknownErrorException: For unexpected failures while stoping.
        """
        logger.info("Received request to stop currently running mission")
        self.anymal.pause_mission(self.current_anymal_mission_id)

        if self.return_to_home_mission_running:
            self.return_to_home_mission_running = False

        self.current_anymal_mission_id = None

    def pause(self) -> None:
        """Pause the currently running mission on the robot.

        This method forwards the pause request to the underlying ANYmal API for
        the mission identified by ``self.current_anymal_mission_id``.

        Raises:
            RobotNoMissionRunningException: If there is no active mission on the robot.
            RobotAPIException: If the underlying robot API returns an error.
            RobotCommunicationException: If the pause request fails due to
                connectivity/transport issues.
            RobotUnknownErrorException: For unexpected failures while pausing.
        """
        logger.info("Received request to pause currently running mission")
        self.anymal.pause_mission(self.current_anymal_mission_id)

    def resume(self) -> None:
        """Resume the currently paused/active mission on the robot.

        This method forwards the resume request to the underlying ANYmal API for
        the mission identified by ``self.current_anymal_mission_id``.

        Raises:
            RobotAPIException: If the underlying robot API returns an error.
            RobotCommunicationException: If the resume request fails due to
                connectivity/transport issues.
            RobotUnknownErrorException: For unexpected failures while resuming.
        """
        logger.info("Received request to resume currently active mission")
        self.anymal.resume_mission(self.current_anymal_mission_id)

    def get_inspection(self, task: InspectionTask) -> Inspection:
        raise NotImplementedError

    def register_inspection_callback(
        self, callback_function: Callable[[Inspection, Mission], None]
    ):
        logger.info("Registering inspection callback")
        self.inspection_handler.register_process_inspection_callback(
            final_callback=callback_function
        )

    def initialize(self) -> None:
        return

    def generate_media_config(self) -> MediaConfig:
        return self.anymal.generate_media_config()

    def get_telemetry_publishers(
        self, queue: Queue, isar_id: str, robot_name: str
    ) -> List[Thread]:
        publisher_threads: List[Thread] = []

        battery_publisher: MqttTelemetryPublisher = MqttTelemetryPublisher(
            mqtt_queue=queue,
            telemetry_method=self.anymal.get_battery_telemetry_payload,
            topic=f"isar/{isar_id}/battery",
            interval=5,
            retain=False,
        )
        battery_thread: Thread = Thread(
            target=battery_publisher.run,
            args=[isar_id, robot_name],
            name="ISAR Robot Battery Publisher",
            daemon=True,
        )
        publisher_threads.append(battery_thread)

        pose_publisher: MqttTelemetryPublisher = MqttTelemetryPublisher(
            mqtt_queue=queue,
            telemetry_method=self.anymal.get_pose_telemetry_payload,
            topic=f"isar/{isar_id}/pose",
            interval=5,
            retain=False,
        )
        pose_thread: Thread = Thread(
            target=pose_publisher.run,
            args=[isar_id, robot_name],
            name="ISAR Robot Pose Publisher",
            daemon=True,
        )
        publisher_threads.append(pose_thread)

        return publisher_threads

    def robot_status(self) -> RobotStatus:
        return self.anymal.get_robot_status()

    def get_battery_level(self) -> float:
        battery_level: Optional[float] = self.anymal.battery_handler.battery.level
        if battery_level is None:
            raise RobotUnknownErrorException("Unable to get battery level from robot")
        return battery_level
