import logging
from typing import Optional

from robot_interface.models.exceptions.robot_exceptions import RobotTelemetryException

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.models import PhysicalConditionEventDto
from isar_anymal.robot.api.sse_handler import SSEHandler

logger = logging.getLogger(__name__)


class MainBodyStateHandler:
    def __init__(self) -> None:
        self.relative_humidity: Optional[float] = None
        self.differential_pressure: Optional[float] = None
        self.temperature: Optional[float] = None
        self.timestamp: Optional[str] = None

        self.main_body_state_sse_handler: SSEHandler = SSEHandler()

        self._register_update_main_body_state_callback()

    def _register_update_main_body_state_callback(self) -> None:
        url: str = (
            f"{settings.SERVER_URL}/anymal-api/events/physical-condition?anymal={settings.ROBOT_NAME}"
        )
        self.main_body_state_sse_handler.activate_sse_listening_thread(
            url=url,
            on_event=self._update_main_body_state_callback,
            model_type=PhysicalConditionEventDto,
        )

    def _update_main_body_state_callback(
        self, event: PhysicalConditionEventDto
    ) -> None:
        try:
            self._set_relative_humidity(event.main_body_state.relative_humidity)
            self._set_differential_pressure(event.main_body_state.differential_pressure)
            self._set_temperature(event.main_body_state.temperature)
            self._set_timestamp(event.timestamp)
        except RobotTelemetryException, Exception:
            logger.exception(
                f"Failed to update main body state from physical condition event: {event}"
            )

    def _set_relative_humidity(self, relative_humidity: float) -> None:
        """Set the ANYmal relative humidity

        :param relative_humidity: The relative humidity measurement value received from
        the callback is expected to be float value.
        """
        self.relative_humidity = relative_humidity

    def _set_differential_pressure(self, differential_pressure: float) -> None:
        """Set the ANYmal differential pressure

        :param differential_pressure: The differential pressure measurement value received from
        the callback is expected to be float value.
        """
        self.differential_pressure = differential_pressure

    def _set_temperature(self, temperature: float) -> None:
        """Set the ANYmal temperature

        :param temperature: The temperature measurement value received from
        the callback is expected to be float value.
        """
        self.temperature = temperature

    def _set_timestamp(self, timestamp: str) -> None:
        """Set the ANYmal timestamp

        :param timestamp: Timestamp for the event given in nanoseconds since epoch
        """
        self.timestamp = timestamp
