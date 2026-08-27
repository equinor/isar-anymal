import itertools
import time
from collections.abc import Callable
from threading import Event, Thread

from isar_anymal.robot.api.sse_handler import SSEHandler


class _FakeResponse:
    def __init__(self) -> None:
        self.closed: bool = False

    def close(self) -> None:
        self.closed = True


class _FailingResponse:
    def close(self) -> None:
        raise OSError("socket already gone")


def test_that_reconnect_closes_the_current_stream():
    handler: SSEHandler = SSEHandler()
    response: _FakeResponse = _FakeResponse()
    handler.current_response = response

    handler.reconnect()

    assert response.closed


def test_that_reconnect_without_an_active_stream_is_a_no_op():
    handler: SSEHandler = SSEHandler()
    handler.reconnect()
    assert handler.current_response is None


def test_that_a_failure_to_close_the_stream_is_not_propagated():
    handler: SSEHandler = SSEHandler()
    handler.current_response = _FailingResponse()

    handler.reconnect()


class _BlockingResponse:
    """A stream that yields nothing until it is closed."""

    def __init__(self) -> None:
        self.released: Event = Event()

    def raise_for_status(self) -> None:
        pass

    def iter_lines(self):
        self.released.wait(timeout=5)
        return iter(())

    def close(self) -> None:
        self.released.set()


def _wait_until(condition: Callable[[], bool], timeout: float = 5) -> bool:
    deadline: float = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_that_closing_the_stream_makes_the_listener_reconnect():
    handler: SSEHandler = SSEHandler()
    connected_twice: Event = Event()
    connection_count: itertools.count = itertools.count(1)

    def fake_get(**_kwargs) -> _BlockingResponse:
        if next(connection_count) > 1:
            connected_twice.set()
        return _BlockingResponse()

    handler.request_handler.get = fake_get
    Thread(
        target=handler.subscribe_to_sse,
        args=("a-url", lambda _event: None, object),
        daemon=True,
    ).start()

    assert _wait_until(lambda: handler.current_response is not None)
    handler.reconnect()

    assert connected_twice.wait(timeout=5)
