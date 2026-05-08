import logging
from typing import Optional, List

from robot_interface.models.exceptions.robot_exceptions import (
    RobotCommunicationException,
    RobotMissionStatusException,
    RobotTaskStatusException,
)
from robot_interface.models.mission.status import MissionStatus, TaskStatus

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.enums import (
    ANYmalTaskStatus,
    Outcome,
    ANYmalMissionStatus,
)
from isar_anymal.robot.api.anymal_api.models import MissionEventDto, TaskSummaryDto
from isar_anymal.robot.api.sse_handler import SSEHandler

logger = logging.getLogger(__name__)


class MissionStatusHandler:
    def __init__(self) -> None:
        self.last_mission_event: Optional[MissionEventDto] = None
        self.mission_status_sse_handler: SSEHandler = SSEHandler()

        self.register_update_mission_event_callback()

    def update_mission_event_callback(self, event: MissionEventDto) -> None:
        self.last_mission_event = event

    def register_update_mission_event_callback(self) -> None:
        url: str = (
            f"{settings.SERVER_URL}/anymal-api/events/mission-progress?anymal={settings.ROBOT_NAME}"
        )
        self.mission_status_sse_handler.activate_sse_listening_thread(
            url=url,
            on_event=self.update_mission_event_callback,
            model_type=MissionEventDto,
        )

    def get_task_status(self, task_id: str) -> TaskStatus:
        task_status: Optional[ANYmalTaskStatus] = None
        task_outcome: Optional[Outcome] = None
        task_summaries: List[TaskSummaryDto] = self._get_anymal_task_summaries()
        for task_summary in task_summaries:
            if task_summary.task_id == task_id:
                task_status = task_summary.status
                task_outcome = task_summary.outcome
            elif task_summary.task_id == "undock":
                if (
                    task_summary.status == ANYmalTaskStatus.TS_COMPLETED
                    and task_summary.outcome == Outcome.OC_FAILURE
                ):
                    return TaskStatus.Failed

        return self._anymal_task_summary_to_task_status(task_status, task_outcome)

    def get_mission_status(self) -> MissionStatus:
        try:
            anymal_mission_status: ANYmalMissionStatus = (
                self._get_anymal_mission_status()
            )
        except RobotCommunicationException:
            return MissionStatus.NotStarted

        if anymal_mission_status == ANYmalMissionStatus.MS_PAUSED:
            return MissionStatus.Paused
        elif anymal_mission_status == ANYmalMissionStatus.MS_RUNNING:
            return MissionStatus.InProgress
        elif anymal_mission_status == ANYmalMissionStatus.MS_NA:
            raise RobotMissionStatusException("Mission status is not available")

        try:
            task_summaries: List[TaskSummaryDto] = self._get_anymal_task_summaries()
            task_statuses = list(
                map(
                    lambda task: self._anymal_task_summary_to_task_status(
                        task.status, task.outcome
                    ),
                    task_summaries,
                )
            )
        except RobotTaskStatusException:
            raise RobotMissionStatusException(
                "Received an unsupported task status, and could therefore not calculate mission status"
            )

        if all(map(lambda status: status == TaskStatus.NotStarted, task_statuses)):
            return MissionStatus.NotStarted
        if any(
            map(
                lambda status: status in [TaskStatus.InProgress, TaskStatus.NotStarted],
                task_statuses,
            )
        ):
            return MissionStatus.InProgress
        if all(map(lambda status: status == TaskStatus.Successful, task_statuses)):
            return MissionStatus.Successful
        if all(map(lambda status: status == TaskStatus.Failed, task_statuses)):
            return MissionStatus.Failed
        if any(map(lambda status: status == TaskStatus.Cancelled, task_statuses)):
            return MissionStatus.Cancelled
        if any(map(lambda status: status == TaskStatus.Failed, task_statuses)):
            return MissionStatus.PartiallySuccessful
        raise RobotMissionStatusException("Unhandled mission status detected")

    def _get_anymal_task_summaries(self) -> List[TaskSummaryDto]:
        if self.last_mission_event is None:
            raise RobotCommunicationException(
                "Tried to retrieve task status before the first mission event was received"
            )
        return self.last_mission_event.mission_summary.task_summaries

    def _get_anymal_mission_status(self) -> ANYmalMissionStatus:
        if self.last_mission_event is None:
            raise RobotCommunicationException(
                "Tried to retrieve mission status before the first mission event was received"
            )

        return self.last_mission_event.mission_summary.status

    @staticmethod
    def _anymal_task_summary_to_task_status(
        task_status: ANYmalTaskStatus, task_outcome: Outcome
    ) -> TaskStatus:
        if task_status == ANYmalTaskStatus.TS_NA:
            logger.error(f"Task status is not available: {task_status}")
            raise RobotTaskStatusException("Task status not available")

        if task_status == ANYmalTaskStatus.TS_COMPLETED:
            if (
                task_outcome == Outcome.OC_SUCCESS
                or task_outcome == Outcome.OC_NORMAL
                # Currently treating anomalies as successful outcomes from ISAR perspective
                or task_outcome == Outcome.OC_ANOMALY
            ):
                return TaskStatus.Successful
            elif task_outcome == Outcome.OC_FAILURE:
                return TaskStatus.Failed
            elif task_outcome == Outcome.OC_NA:
                raise RobotTaskStatusException("Task outcome not available")
            else:
                raise RobotTaskStatusException(
                    f"Received an unsupported task outcome: {task_outcome}"
                )
        elif task_status == ANYmalTaskStatus.TS_ONGOING:
            return TaskStatus.InProgress
        elif task_status == ANYmalTaskStatus.TS_UPCOMING:
            return TaskStatus.NotStarted
        elif task_status == ANYmalTaskStatus.TS_PREEMPTED:
            return TaskStatus.Paused

        logger.error(f"Received an unsupported task status: {task_status}")
        raise RobotTaskStatusException("Received an unsupported task status")
