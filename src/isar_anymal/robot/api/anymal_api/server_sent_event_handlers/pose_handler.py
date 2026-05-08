from typing import Optional

from alitra import (
    Pose,
    Position,
    Frame,
    Orientation,
    Transform,
)
import logging
from robot_interface.models.exceptions.robot_exceptions import RobotTelemetryException


from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.models import StateEventDto, PoseValueDto
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.utilities import (
    import_transform_from_map_file,
)
from isar_anymal.robot.api.sse_handler import SSEHandler

logger = logging.getLogger(__name__)


class PoseHandler:
    def __init__(self):
        self.pose: Optional[Pose] = None
        self.timestamp: Optional[str] = None
        self.pose_sse_handler: SSEHandler = SSEHandler()
        self.transform: Transform = import_transform_from_map_file()

        self.register_update_pose_callback()

    def set_pose(self, pose_value: PoseValueDto) -> None:
        """Set the ANYmal pose

        :param pose_value: The pose value received from the callback is expected to be of type
        PoseValueDto.
        """
        try:
            pose = Pose(
                position=Position(
                    x=pose_value.position.x,
                    y=pose_value.position.y,
                    z=pose_value.position.z,
                    frame=Frame("robot"),
                ),
                orientation=Orientation(
                    x=pose_value.orientation.qx,
                    y=pose_value.orientation.qy,
                    z=pose_value.orientation.qz,
                    w=pose_value.orientation.qw,
                    frame=Frame("robot"),
                ),
                frame=Frame("robot"),
            )
        except (AttributeError, TypeError) as e:
            raise RobotTelemetryException("Could not get robot pose") from e

        if pose.orientation == Orientation(x=0, y=0, z=0, w=0, frame=Frame("robot")):
            # Avoid zero norm
            pose.orientation.w = 1

        self.pose = self.transform.transform_pose(
            pose, from_=Frame("robot"), to_=Frame("asset")
        )

    def set_timestamp(self, timestamp: str) -> None:
        """Set the ANYmal battery timestamp

        :param timestamp: Timestamp for the event given in nanoseconds since epoch
        """
        self.timestamp = timestamp

    def update_pose_callback(self, event: StateEventDto) -> None:
        try:
            self.set_pose(event.pose.pose.value)
            self.set_timestamp(event.timestamp)
        except RobotTelemetryException, Exception:
            logger.exception(f"Failed to update ANYmal pose from event: {event}")

    def register_update_pose_callback(self) -> None:
        url: str = (
            f"{settings.SERVER_URL}/anymal-api/events/state?anymal={settings.ROBOT_NAME}"
        )
        self.pose_sse_handler.activate_sse_listening_thread(
            url=url,
            on_event=self.update_pose_callback,
            model_type=StateEventDto,
        )
