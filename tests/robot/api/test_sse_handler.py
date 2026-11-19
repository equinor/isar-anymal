import logging
from unittest.mock import MagicMock

import pytest
from requests import ConnectionError, ConnectTimeout
from urllib3.exceptions import ReadTimeoutError

from isar_anymal.robot.api import sse_handler
from isar_anymal.robot.api.sse_handler import SSEHandler

URL = "http://robot/events"


class FakeClock:
    """Replaces time.sleep/time.monotonic and stops the listener after N sleeps."""

    def __init__(self) -> None:
        self.now: float = 0
        self.sleeps: list[float] = []
        self.max_sleeps: int = 0

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        if len(self.sleeps) >= self.max_sleeps:
            raise StopIteration
        self.now += delay

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake_clock = FakeClock()
    monkeypatch.setattr(sse_handler.time, "sleep", fake_clock.sleep)
    monkeypatch.setattr(sse_handler.time, "monotonic", fake_clock.monotonic)
    return fake_clock


def _stream(
    clock: FakeClock,
    lines=(),
    error: Exception | None = None,
    duration: float = 0,
) -> MagicMock:
    response = MagicMock()

    def iter_lines():
        yield from lines
        clock.now += duration
        if error is not None:
            raise error

    response.iter_lines.side_effect = iter_lines
    return response


def _idle_stream(clock: FakeClock) -> MagicMock:
    error = ConnectionError(ReadTimeoutError(None, URL, "Read timed out."))
    return _stream(clock, error=error, duration=sse_handler.SSE_READ_TIMEOUT)


def _run(clock: FakeClock, responses: list, max_sleeps: int) -> None:
    clock.max_sleeps = max_sleeps
    handler = SSEHandler()
    handler.request_handler = MagicMock()
    handler.request_handler.get.side_effect = responses
    with pytest.raises(StopIteration):
        handler.subscribe_to_sse(URL, MagicMock(), MagicMock())
    for call in handler.request_handler.get.call_args_list:
        assert call.kwargs["request_timeout"] == (10, 30)
        assert call.kwargs["stream"] is True


def _messages(caplog, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == level]


def test_idle_stream_reconnects_promptly_without_warnings(clock, caplog):
    caplog.set_level(logging.DEBUG, logger=sse_handler.__name__)
    responses = [_idle_stream(clock) for _ in range(3)]

    _run(clock, responses, max_sleeps=3)

    assert clock.sleeps == [0.1, 0.1, 0.1]
    assert _messages(caplog, logging.WARNING) == []
    assert _messages(caplog, logging.INFO) == [f"Connected to SSE endpoint {URL}"]
    for response in responses:
        response.close.assert_called_once()


def test_silent_broken_connection_backs_off_and_warns(clock, caplog):
    responses = [_idle_stream(clock), ConnectTimeout(), ConnectTimeout()]

    _run(clock, responses, max_sleeps=3)

    assert clock.sleeps == [0.1, 0.2, 0.4]
    warnings = _messages(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "ConnectTimeout" in warnings[0]


def test_stream_closing_without_data_does_not_reset_backoff(clock, caplog):
    _run(clock, [_stream(clock), _stream(clock), _stream(clock)], max_sleeps=3)

    assert clock.sleeps == [0.1, 0.2, 0.4]
    assert "without delivering data" in _messages(caplog, logging.WARNING)[0]


def test_connection_refusal_warnings_are_rate_limited(clock, caplog):
    responses = [ConnectionError("Connection refused")] * 11

    _run(clock, responses, max_sleeps=11)

    assert clock.sleeps == [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 25.6, 30, 30]
    warnings = _messages(caplog, logging.WARNING)
    assert len(warnings) == 2
    assert "1 consecutive failure(s)" in warnings[0]
    assert "11 consecutive failure(s) over 81s" in warnings[1]


def test_recovery_is_logged_and_resets_backoff(clock, caplog):
    caplog.set_level(logging.INFO, logger=sse_handler.__name__)
    responses = [
        ConnectionError("Connection refused"),
        ConnectionError("Connection refused"),
        _stream(clock, lines=[b": heartbeat"], error=ConnectionError("reset")),
    ]

    _run(clock, responses, max_sleeps=3)

    assert clock.sleeps == [0.1, 0.2, 0.1]
    assert (
        f"SSE connection to {URL} recovered after 2 consecutive failure(s) over 0s"
        in _messages(caplog, logging.INFO)
    )
    warnings = _messages(caplog, logging.WARNING)
    assert len(warnings) == 2
    assert "1 consecutive failure(s)" in warnings[1]
