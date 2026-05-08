import logging
from typing import Optional

from pydantic import BaseModel
from robot_interface.models.exceptions.robot_exceptions import RobotTelemetryException
from robot_interface.models.robots.battery_state import BatteryState

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.enums import BatteryStatus
from isar_anymal.robot.api.anymal_api.models import PhysicalConditionEventDto
from isar_anymal.robot.api.sse_handler import SSEHandler

logger = logging.getLogger(__name__)


class Battery(BaseModel):
    level: Optional[float]
    state: Optional[BatteryState]
    timestamp: Optional[str]


class BatteryHandler:
    def __init__(self) -> None:
        self.battery: Battery = Battery(level=None, state=None, timestamp=None)
        self.anymal_reported_battery_status: Optional[BatteryStatus] = None

        self.battery_sse_handler: SSEHandler = SSEHandler()

        self.register_update_battery_callback()

    def set_battery_level(self, state_of_charge: float) -> None:
        """Set the ANYmal battery level

        :param state_of_charge: The battery state of charge measurement value received from
        the callback is expected to be a float value between 0 - 1.
        """
        if state_of_charge < 0.0 or state_of_charge > 1.0:
            raise RobotTelemetryException("Invalid battery level")

        battery_level: float = state_of_charge * 100.0

        if battery_level != self.battery.level:
            self.battery.level = battery_level

    def set_battery_state(self, battery_status: BatteryStatus) -> None:
        """Set the ANYmal battery state

        :param battery_status: The battery status received from the callback is expected to
        be an enum of type BatteryStatus.
        """
        self.anymal_reported_battery_status = battery_status

        try:
            new_battery_state = self._map_battery_status_to_battery_state(
                battery_status
            )
        except RobotTelemetryException:
            # We don't log the stack trace for RobotTelemetryException as it is caused by BatteryStatus being
            # NOT_CONNECTED or ERROR. This reduces clutter in our logs.
            self.battery.state = None
            return
        except Exception:
            logger.exception(
                f"Battery state set to none as update of new value from battery status: {battery_status} "
                f"failed and the value can no longer be trusted"
            )
            self.battery.state = None
            return

        if new_battery_state != self.battery.state:
            logger.info(
                f"Battery state changed from {self.battery.state} to {new_battery_state}"
            )
            self.battery.state = new_battery_state

    def set_timestamp(self, timestamp: str) -> None:
        """Set the ANYmal battery timestamp

        :param timestamp: Timestamp for the event given in nanoseconds since epoch
        """
        self.battery.timestamp = timestamp

    def update_battery_callback(self, event: PhysicalConditionEventDto) -> None:
        try:
            self.set_battery_level(event.battery_state.state_of_charge)
            self.set_battery_state(event.battery_state.status)
            self.set_timestamp(event.timestamp)
        except RobotTelemetryException, Exception:
            logger.exception(
                f"Failed to update battery from physical condition event: {event}"
            )

    def register_update_battery_callback(self) -> None:
        url: str = (
            f"{settings.SERVER_URL}/anymal-api/events/physical-condition?anymal={settings.ROBOT_NAME}"
        )
        self.battery_sse_handler.activate_sse_listening_thread(
            url=url,
            on_event=self.update_battery_callback,
            model_type=PhysicalConditionEventDto,
        )

    @staticmethod
    def _map_battery_status_to_battery_state(
        battery_status: BatteryStatus,
    ) -> BatteryState:
        if battery_status == BatteryStatus.BS_CHARGING:
            return BatteryState.Charging
        elif battery_status == BatteryStatus.BS_DISCHARGING:
            return BatteryState.Normal
        else:
            error_description: str = (
                f"Received unhandled battery status: {battery_status}"
            )
            logger.error(error_description)
            raise RobotTelemetryException(error_description)
