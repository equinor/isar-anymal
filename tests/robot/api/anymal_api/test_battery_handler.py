import logging

import pytest
from pytest_mock import MockerFixture
from robot_interface.models.exceptions.robot_exceptions import (
    RobotTelemetryNoUpdateException,
)
from robot_interface.models.robots.battery_state import BatteryState

from isar_anymal.robot.api.anymal_api.enums import BatteryStatus
from isar_anymal.robot.api.anymal_api.models import (
    BatteryStateDto,
    PhysicalConditionEventDto,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.battery_handler import (
    BatteryHandler,
)
from isar_anymal.robot.api.api import API
from tests.robot.utilities import mock_subscribe_callback_functions

UNAVAILABLE_STATUSES = [
    BatteryStatus.BS_UNKNOWN,
    BatteryStatus.BS_NOT_CONNECTED,
    BatteryStatus.BS_ERROR,
    BatteryStatus.BS_PERMANENT_FAILURE,
    BatteryStatus.UNRECOGNIZED,
]


@pytest.fixture
def battery_handler(mocker: MockerFixture) -> BatteryHandler:
    mocker.patch.object(BatteryHandler, "register_update_battery_callback")
    return BatteryHandler()


@pytest.mark.parametrize("status", UNAVAILABLE_STATUSES)
def test_unavailable_status_logs_once_per_transition(
    battery_handler: BatteryHandler,
    status: BatteryStatus,
    caplog: pytest.LogCaptureFixture,
) -> None:
    battery_handler.set_battery_state(BatteryStatus.BS_CHARGING)

    for _ in range(100):
        battery_handler.set_battery_state(status)

    assert battery_handler.battery.state is None
    assert battery_handler.anymal_reported_battery_status == status
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert str(status) in caplog.records[0].message
    assert caplog.records[0].exc_info is None


def test_distinct_unavailable_statuses_each_log_an_error(
    battery_handler: BatteryHandler, caplog: pytest.LogCaptureFixture
) -> None:
    statuses = [
        BatteryStatus.BS_NOT_CONNECTED,
        BatteryStatus.BS_ERROR,
        BatteryStatus.BS_PERMANENT_FAILURE,
        BatteryStatus.BS_NOT_CONNECTED,
    ]

    for status in statuses:
        battery_handler.set_battery_state(status)
        battery_handler.set_battery_state(status)
        assert battery_handler.battery.state is None

    assert len(caplog.records) == len(statuses)
    for status, record in zip(statuses, caplog.records):
        assert record.levelno == logging.ERROR
        assert str(status) in record.message


@pytest.mark.parametrize("status", UNAVAILABLE_STATUSES)
@pytest.mark.parametrize(
    "recovery_status, expected_state",
    [
        (BatteryStatus.BS_CHARGING, BatteryState.Charging),
        (BatteryStatus.BS_DISCHARGING, BatteryState.Normal),
    ],
)
def test_recovery_restores_state_and_resets_error_logging(
    battery_handler: BatteryHandler,
    status: BatteryStatus,
    recovery_status: BatteryStatus,
    expected_state: BatteryState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    battery_handler.set_battery_state(status)
    battery_handler.set_battery_state(recovery_status)

    assert battery_handler.battery.state == expected_state
    assert battery_handler.anymal_reported_battery_status == recovery_status

    battery_handler.set_battery_state(status)

    assert battery_handler.battery.state is None
    assert len(caplog.records) == 2
    assert all(record.levelno == logging.ERROR for record in caplog.records)


def test_repeated_disconnected_events_still_update_level_and_timestamp(
    battery_handler: BatteryHandler, caplog: pytest.LogCaptureFixture
) -> None:
    for index in range(2):
        battery_handler.update_battery_callback(
            PhysicalConditionEventDto(
                timestamp=str(index),
                batteryState=BatteryStateDto(
                    stateOfCharge=0.5 + index * 0.1,
                    voltage=48.0,
                    status=BatteryStatus.BS_NOT_CONNECTED,
                ),
            )
        )

    assert battery_handler.battery.level == pytest.approx(60.0)
    assert battery_handler.battery.timestamp == "1"
    assert battery_handler.battery.state is None
    assert (
        battery_handler.anymal_reported_battery_status == BatteryStatus.BS_NOT_CONNECTED
    )
    assert len(caplog.records) == 1


@pytest.mark.parametrize("status", UNAVAILABLE_STATUSES)
def test_unavailable_battery_is_not_published_as_healthy_or_home(
    mocker: MockerFixture, status: BatteryStatus
) -> None:
    mock_subscribe_callback_functions(mocker)
    anymal = API()
    anymal.battery_handler.set_battery_level(1.0)
    anymal.battery_handler.set_battery_state(BatteryStatus.BS_CHARGING)
    anymal.battery_handler.set_battery_state(status)

    assert anymal.get_battery_status() == status
    with pytest.raises(RobotTelemetryNoUpdateException, match="battery state"):
        anymal.get_battery_state()
    with pytest.raises(RobotTelemetryNoUpdateException, match="battery state"):
        anymal.get_battery_telemetry_payload()
    with pytest.raises(RobotTelemetryNoUpdateException, match="battery state"):
        anymal.robot_is_home()
