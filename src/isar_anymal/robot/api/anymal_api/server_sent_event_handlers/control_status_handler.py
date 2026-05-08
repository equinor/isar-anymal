from typing import Optional

from pydantic import BaseModel

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.enums import ClientType, UserInteractionMode
from isar_anymal.robot.api.anymal_api.models import ControlStatusEventDto
from isar_anymal.robot.api.sse_handler import SSEHandler


class ControlStatus(BaseModel):
    client_name: Optional[str]
    client_type: Optional[ClientType]
    protective_stop_engaged: Optional[bool]
    is_power_cut: Optional[bool]
    user_interaction_mode: Optional[UserInteractionMode]
    timestamp: Optional[str]


class ControlStatusHandler:
    def __init__(self):
        self.control_status: ControlStatus = ControlStatus(
            client_name=None,
            client_type=None,
            protective_stop_engaged=None,
            is_power_cut=None,
            user_interaction_mode=None,
            timestamp=None,
        )

        self.control_status_sse_handler: SSEHandler = SSEHandler()
        self.register_update_control_status_callback()

    def update_control_status_callback(self, event: ControlStatusEventDto) -> None:
        self.control_status.client_name = (
            event.control_authority_status.client_name
            if event.control_authority_status is not None
            else self.control_status.client_name
        )
        self.control_status.client_type = (
            event.control_authority_status.client_type
            if event.control_authority_status is not None
            else self.control_status.client_type
        )
        self.control_status.protective_stop_engaged = (
            event.protective_stop_status.is_engaged
        )
        self.control_status.is_power_cut = event.is_power_cut
        self.control_status.user_interaction_mode = (
            event.user_interaction_mode
            if event.user_interaction_mode is not None
            else self.control_status.user_interaction_mode
        )
        self.control_status.timestamp = event.timestamp

    def register_update_control_status_callback(self) -> None:
        url: str = (
            f"{settings.SERVER_URL}/anymal-api/events/control-status?anymal={settings.ROBOT_NAME}"
        )
        self.control_status_sse_handler.activate_sse_listening_thread(
            url=url,
            on_event=self.update_control_status_callback,
            model_type=ControlStatusEventDto,
        )
