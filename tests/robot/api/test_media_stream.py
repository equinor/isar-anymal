from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Barrier, Event
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture
from requests import HTTPError, Timeout

from isar_anymal.config import settings
from isar_anymal.robot.api.api import API
from isar_anymal.robot.api.media_stream import MediaStream
from isar_anymal.robot.api.request_handler import RequestHandler
from tests.robot.utilities import mock_subscribe_callback_functions

MODULE = "isar_anymal.robot.api.media_stream.media_stream"
READY = [{"frameId": "front_camera", "state": 1}]
OFFLINE = [{"frameId": "front_camera", "state": 0}]


@dataclass
class Clock:
    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(mocker: MockerFixture) -> Clock:
    clock = Clock()
    mocker.patch(f"{MODULE}.time", clock)
    return clock


@pytest.fixture
def handler() -> Mock:
    handler = Mock(spec=RequestHandler)
    handler.get.return_value.json.return_value = {"sources": OFFLINE}
    return handler


def set_source_sequence(handler: Mock, *results) -> None:
    sequence = iter(results)

    def get(**kwargs):
        result = next(sequence, OFFLINE)
        if isinstance(result, Exception):
            raise result
        return Mock(json=Mock(return_value={"sources": result}))

    handler.get.side_effect = get


def test_outage_recovers_with_fresh_tracks(
    handler: Mock, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    recovered = [
        {"frameId": "replacement_camera", "state": 1},
        {"frameId": "acoustic_camera", "state": 1},
    ]
    set_source_sequence(handler, READY, OFFLINE, recovered)
    caplog.set_level("INFO", logger=MODULE)

    MediaStream(handler).activate_when_active_and_keep_active()

    assert [call.kwargs["json_body"] for call in handler.post.call_args_list] == [
        {"tracks": [{"frameId": "front_camera"}]},
        {
            "tracks": [
                {"frameId": "replacement_camera"},
                {"frameId": "acoustic_camera"},
            ]
        },
    ]
    assert clock.sleeps[:3] == [3, 5, 3]
    assert clock.now == 908  # A successful recovery at t=8 resets the window.
    assert caplog.text.count("Media stream keepalives active") == 2
    assert caplog.text.count("attempting bounded recovery") == 2
    assert "recovery expired" in caplog.text


@pytest.mark.parametrize("initial_failure", [True, False])
def test_source_request_errors_recover(
    handler: Mock, clock: Clock, initial_failure: bool
) -> None:
    prefix = [] if initial_failure else [READY]
    set_source_sequence(handler, *prefix, Timeout(), HTTPError("404"), READY)

    MediaStream(handler).activate_when_active_and_keep_active()

    assert handler.post.call_count == (1 if initial_failure else 2)
    assert clock.now == (915 if initial_failure else 918)


def test_failed_keepalive_retries_with_refreshed_sources(
    handler: Mock, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    replacement = [{"frameId": "replacement_camera", "state": 1}]
    set_source_sequence(handler, READY, READY, replacement, replacement)
    handler.post.side_effect = [None, HTTPError("404"), Timeout("timeout"), None]
    caplog.set_level("INFO", logger=MODULE)

    MediaStream(handler).activate_when_active_and_keep_active()

    assert handler.post.call_count == 4
    assert handler.post.call_args.kwargs["json_body"] == {
        "tracks": [{"frameId": "replacement_camera"}]
    }
    assert clock.sleeps[:4] == [3, 5, 10, 3]
    assert clock.now == 918
    assert caplog.text.count("Media stream request failed") == 1


@pytest.mark.parametrize(
    "sources",
    [[], OFFLINE, [{"frameId": "acoustic_camera", "state": 1}]],
)
def test_unavailable_sources_expire_without_activation(
    handler: Mock, clock: Clock, sources: list[dict]
) -> None:
    handler.get.return_value.json.return_value = {"sources": sources}

    MediaStream(handler).activate_when_active_and_keep_active()

    handler.post.assert_not_called()
    assert clock.now == 900
    assert clock.sleeps[:4] == [5, 10, 20, 30]
    assert max(clock.sleeps) == 30
    assert clock.sleeps[-1] == 25


@pytest.mark.parametrize("failure", ["sources", "tracks"])
def test_persistent_request_errors_expire(
    handler: Mock, clock: Clock, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    if failure == "sources":
        handler.get.side_effect = Timeout("offline")
    else:
        handler.get.return_value.json.return_value = {"sources": READY}
        handler.post.side_effect = HTTPError("404")

    MediaStream(handler).activate_when_active_and_keep_active()

    assert clock.now == 900
    assert caplog.text.count("Media stream request failed") == 1
    for call in handler.get.call_args_list + handler.post.call_args_list:
        assert 0 < call.kwargs["request_timeout"] <= settings.API_REQUEST_TIMEOUT
    assert handler.get.call_args.kwargs["request_timeout"] == min(
        25, settings.API_REQUEST_TIMEOUT
    )


@pytest.mark.parametrize("elapsed", [899, 900])
def test_source_request_time_counts_toward_recovery_window(
    handler: Mock, clock: Clock, elapsed: float
) -> None:
    def get(**kwargs):
        clock.now += elapsed
        return Mock(json=Mock(return_value={"sources": READY}))

    handler.get.side_effect = get
    handler.post.side_effect = Timeout()

    MediaStream(handler).activate_when_active_and_keep_active()

    assert clock.now == 900
    if elapsed == 899:
        assert handler.post.call_args.kwargs["request_timeout"] == 1
        assert clock.sleeps == [1]
    else:
        handler.post.assert_not_called()
        assert clock.sleeps == []


def test_unexpected_errors_surface(handler: Mock, clock: Clock) -> None:
    handler.get.side_effect = RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        MediaStream(handler).activate_when_active_and_keep_active()

    assert clock.sleeps == []


def test_fresh_media_config_restarts_expired_worker(
    handler: Mock, clock: Clock, mocker: MockerFixture
) -> None:
    mock_subscribe_callback_functions(mocker)
    api = API()
    api.media_stream.request_handler = handler
    mocker.patch.object(
        api.media_stream,
        "get_liveview_info",
        return_value=("wss://liveview.example", "token"),
    )

    api.generate_media_config()
    first_worker = api.media_stream.activate_stream_thread
    assert first_worker is not None
    first_worker.join(timeout=5)
    assert not api.media_stream.is_active()
    assert clock.now == 900

    api.generate_media_config()
    second_worker = api.media_stream.activate_stream_thread
    assert second_worker is not None
    second_worker.join(timeout=5)
    assert second_worker is not first_worker
    assert not api.media_stream.is_active()
    assert clock.now == 1800


def test_concurrent_activation_owns_one_worker(
    handler: Mock, mocker: MockerFixture
) -> None:
    stream = MediaStream(handler)
    release_worker = Event()
    entered_worker = Event()
    callers = Barrier(8)

    def run_worker() -> None:
        entered_worker.set()
        assert release_worker.wait(timeout=5)

    worker = mocker.patch.object(
        stream, "activate_when_active_and_keep_active", side_effect=run_worker
    )

    def activate() -> None:
        callers.wait(timeout=5)
        stream.activate_stream()

    assert not stream.is_active()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: activate(), range(8)))
        assert entered_worker.wait(timeout=5)
        assert stream.is_active()
        worker.assert_called_once()
    finally:
        release_worker.set()
        if stream.activate_stream_thread is not None:
            stream.activate_stream_thread.join(timeout=5)

    assert not stream.is_active()
