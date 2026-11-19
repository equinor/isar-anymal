import pytest
from pytest_mock import MockerFixture

from isar_anymal.robot.api.anymal_api.enums import (
    ClientType,
    ProtectiveStopOrigin,
    UserInteractionMode,
)
from isar_anymal.robot.api.anymal_api.models import (
    ControlAuthorityStatusDto,
    ControlStatusEventDto,
    ProtectiveStopStatusDto,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.control_status_handler import (
    ControlStatusHandler,
)


@pytest.fixture
def control_status_handler(mocker: MockerFixture) -> ControlStatusHandler:
    mocker.patch.object(ControlStatusHandler, "register_update_control_status_callback")
    return ControlStatusHandler()


def _event(
    is_engaged: bool | None, timestamp: str = "1", is_power_cut: bool = False
) -> ControlStatusEventDto:
    return ControlStatusEventDto(
        timestamp=timestamp,
        isPowerCut=is_power_cut,
        controlAuthorityStatus=ControlAuthorityStatusDto(
            clientName="client", clientType=ClientType.CLCT_REMOTE
        ),
        protectiveStopStatus=(
            None
            if is_engaged is None
            else ProtectiveStopStatusDto(
                isEngaged=is_engaged, origin=ProtectiveStopOrigin.PSO_GUI
            )
        ),
        userInteractionMode=UserInteractionMode.UIM_AUTONOMOUS,
    )


@pytest.mark.parametrize("is_engaged", [True, False])
def test_explicit_protective_stop_status_is_stored(
    control_status_handler: ControlStatusHandler, is_engaged: bool
) -> None:
    control_status_handler.update_control_status_callback(_event(is_engaged))

    assert control_status_handler.control_status.protective_stop_engaged is is_engaged


def test_missing_protective_stop_before_known_value_stays_unknown(
    control_status_handler: ControlStatusHandler,
) -> None:
    control_status_handler.update_control_status_callback(
        _event(None, timestamp="42", is_power_cut=True)
    )

    status = control_status_handler.control_status
    assert status.protective_stop_engaged is None
    assert status.is_power_cut is True
    assert status.timestamp == "42"
    assert status.client_name == "client"
    assert status.client_type == ClientType.CLCT_REMOTE
    assert status.user_interaction_mode == UserInteractionMode.UIM_AUTONOMOUS


@pytest.mark.parametrize("is_engaged", [True, False])
def test_missing_protective_stop_after_known_value_keeps_previous_value(
    control_status_handler: ControlStatusHandler, is_engaged: bool
) -> None:
    control_status_handler.update_control_status_callback(_event(is_engaged))
    control_status_handler.update_control_status_callback(
        _event(None, timestamp="2", is_power_cut=True)
    )

    status = control_status_handler.control_status
    assert status.protective_stop_engaged is is_engaged
    assert status.is_power_cut is True
    assert status.timestamp == "2"
