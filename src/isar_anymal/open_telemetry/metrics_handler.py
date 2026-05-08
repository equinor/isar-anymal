import logging
from typing import List

from alitra import Pose
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation, Meter
from robot_interface.models.exceptions.robot_exceptions import (
    RobotTelemetryNoUpdateException,
    RobotException,
    RobotTelemetryPoseException,
)

from isar_anymal.robot.api import API
from isar_anymal.robot.api.anymal_api.enums import BATTERY_STATUS_TO_INTEGER_MAPPING
from isar_anymal.robot.api.utilities.iteration import iter_numeric

logger = logging.getLogger(__name__)


class MetricsHandler:
    def __init__(self, anymal_api: API, robot_name: str, isar_id: str) -> None:
        self.anymal_api = anymal_api
        self.robot_name = robot_name
        self.isar_id = isar_id

        self.meter: "Meter" = metrics.get_meter("isar.anymal")
        self._setup_observable_gauges()

    def _setup_observable_gauges(self) -> None:
        self.meter.create_observable_gauge(
            name="robot.pose",
            callbacks=[self._observe_robot_pose],
            description="Current pose of the robot in the asset frame",
        )

        self.meter.create_observable_gauge(
            name="robot.battery.level",
            callbacks=[self._observe_battery_level],
            unit="%",
            description="Current battery level of the robot",
        )

        self.meter.create_observable_gauge(
            name="robot.battery.status",
            callbacks=[self._observe_battery_status],
            description="Current internal battery status of the robot",
        )

        self.meter.create_observable_gauge(
            name="robot.main_body.relative_humidity",
            callbacks=[self._observe_relative_humidity],
            description="Current relative humidity of the robot main body",
        )

        self.meter.create_observable_gauge(
            name="robot.main_body.differential_pressure",
            callbacks=[self._observe_differential_pressure],
            description="Current differential pressure of the robot main body",
        )

        self.meter.create_observable_gauge(
            name="robot.main_body.temperature",
            callbacks=[self._observe_temperature],
            unit="C",
            description="Current temperature of the robot main body",
        )

    def _observe_robot_pose(self, _: CallbackOptions) -> List[Observation]:
        observations: List[Observation] = []
        try:
            pose: Pose = self.anymal_api.get_robot_pose()
        except RobotTelemetryPoseException, RobotException:
            return []

        for name, value in iter_numeric(pose.position, excluded_fields=["frame"]):
            observations.append(
                Observation(
                    value=value,
                    attributes={
                        "robot_name": self.robot_name,
                        "isar_id": self.isar_id,
                        "coordinate": f"{name}_position",
                    },
                )
            )

        for name, value in iter_numeric(pose.orientation, excluded_fields=["frame"]):
            observations.append(
                Observation(
                    value=value,
                    attributes={
                        "robot_name": self.robot_name,
                        "isar_id": self.isar_id,
                        "coordinate": f"{name}_orientation",
                    },
                )
            )

        return observations

    def _observe_battery_level(self, _: CallbackOptions) -> List[Observation]:
        try:
            observations: List[Observation] = [
                Observation(
                    value=self.anymal_api.get_battery_level(),
                    attributes={"robot_name": self.robot_name, "isar_id": self.isar_id},
                )
            ]
            return observations
        except RobotTelemetryNoUpdateException, RobotException:
            return []

    def _observe_battery_status(self, _: CallbackOptions) -> List[Observation]:
        try:
            observations: List[Observation] = [
                Observation(
                    value=BATTERY_STATUS_TO_INTEGER_MAPPING[
                        self.anymal_api.get_battery_status()
                    ],
                    attributes={"robot_name": self.robot_name, "isar_id": self.isar_id},
                )
            ]
            return observations
        except RobotTelemetryNoUpdateException, RobotException:
            return []

    def _observe_relative_humidity(self, _: CallbackOptions) -> List[Observation]:
        try:
            observations: List[Observation] = [
                Observation(
                    value=self.anymal_api.get_relative_humidity(),
                    attributes={"robot_name": self.robot_name, "isar_id": self.isar_id},
                )
            ]
            return observations
        except RobotTelemetryNoUpdateException, RobotException:
            return []

    def _observe_differential_pressure(self, _: CallbackOptions) -> List[Observation]:
        try:
            observations: List[Observation] = [
                Observation(
                    value=self.anymal_api.get_differential_pressure(),
                    attributes={"robot_name": self.robot_name, "isar_id": self.isar_id},
                )
            ]
            return observations
        except RobotTelemetryNoUpdateException, RobotException:
            return []

    def _observe_temperature(self, _: CallbackOptions) -> List[Observation]:
        try:
            observations: List[Observation] = [
                Observation(
                    value=self.anymal_api.get_temperature(),
                    attributes={"robot_name": self.robot_name, "isar_id": self.isar_id},
                )
            ]
            return observations
        except RobotTelemetryNoUpdateException, RobotException:
            return []
