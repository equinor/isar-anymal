import json
import logging
import time
from collections.abc import Callable
from threading import Thread
from typing import TypeVar

from pydantic import ValidationError
from requests import ConnectionError, JSONDecodeError, ReadTimeout, Response, Timeout
from requests.exceptions import ChunkedEncodingError
from urllib3.exceptions import ProtocolError, ReadTimeoutError

from isar_anymal.robot.api.anymal_api.models import EventBaseModel
from isar_anymal.robot.api.request_handler import RequestHandler

logger = logging.getLogger(__name__)

TEventModel = TypeVar("TEventModel", bound=EventBaseModel)

# Reconnect backoff: how long to wait before reconnecting a dropped SSE stream.
# The wait doubles after every consecutive failure (0.1s, 0.2s, 0.4s, ... up to
# 30s) so an unreachable server is not hammered with reconnect attempts. It goes
# back to the initial delay once a stream has proven healthy, i.e. it delivered
# data or stayed open for the full read timeout.
SSE_RECONNECT_INITIAL_DELAY: float = 0.1
SSE_RECONNECT_MAX_DELAY: float = 30

# The read timeout drops connections that silently died, e.g. after a network
# restart. The ANYmal event streams can be quiet for much longer than this
# without being broken, so a read timeout on an open stream is logged at debug
# and reconnected immediately instead of being reported as a failure.
SSE_CONNECT_TIMEOUT: float = 10
SSE_READ_TIMEOUT: float = 30

# Minimum time between warnings for consecutive failures of the same stream.
SSE_FAILURE_WARNING_INTERVAL: float = 60


class _SSEConnectionHealth:
    """Summarizes consecutive failures of one SSE stream and logs its recovery."""

    def __init__(self, url: str) -> None:
        self.url: str = url
        self.consecutive_failures: int = 0
        self.first_failure_at: float = 0
        self.last_warning_at: float | None = None

    def record_failure(
        self, reason: str, reconnect_delay: float, unexpected: bool = False
    ) -> None:
        now: float = time.monotonic()
        if self.consecutive_failures == 0:
            self.first_failure_at = now
        self.consecutive_failures += 1

        should_warn: bool = (
            self.last_warning_at is None
            or now - self.last_warning_at >= SSE_FAILURE_WARNING_INTERVAL
        )
        if should_warn:
            self.last_warning_at = now
            level: int = logging.ERROR if unexpected else logging.WARNING
        else:
            level = logging.DEBUG
        logger.log(
            level,
            f"SSE connection to {self.url} failed ({reason}); "
            f"{self.consecutive_failures} consecutive failure(s) over "
            f"{now - self.first_failure_at:.0f}s, reconnecting in {reconnect_delay:g}s",
            exc_info=unexpected and should_warn,
        )

    def record_healthy(self) -> None:
        if self.consecutive_failures > 0:
            logger.info(
                f"SSE connection to {self.url} recovered after "
                f"{self.consecutive_failures} consecutive failure(s) over "
                f"{time.monotonic() - self.first_failure_at:.0f}s"
            )
        self.consecutive_failures = 0
        self.last_warning_at = None


def _is_read_timeout(error: Exception) -> bool:
    # requests wraps read timeouts raised while streaming in a ConnectionError.
    if isinstance(error, ReadTimeout):
        return True
    return isinstance(error, ConnectionError) and any(
        isinstance(arg, ReadTimeoutError) for arg in error.args
    )


class SSEHandler:
    def __init__(self):
        self.request_handler: RequestHandler = RequestHandler()
        self.sse_listening_thread: Thread | None = None

    def activate_sse_listening_thread(
        self,
        url: str,
        on_event: Callable[[TEventModel], None],
        model_type: type[TEventModel],
    ) -> None:
        if (
            self.sse_listening_thread is not None
            and self.sse_listening_thread.is_alive()
        ):
            logger.warning("SSE listening thread is already active")
            return

        self.sse_listening_thread = Thread(
            target=self.subscribe_to_sse,
            args=(url, on_event, model_type),
            daemon=True,
        )
        self.sse_listening_thread.start()

    def subscribe_to_sse(
        self,
        url: str,
        on_event: Callable[[TEventModel], None],
        model_type: TEventModel,
    ) -> None:
        reconnect_delay: float = SSE_RECONNECT_INITIAL_DELAY
        health: _SSEConnectionHealth = _SSEConnectionHealth(url)
        has_connected: bool = False
        while True:
            try:
                response: Response = self.request_handler.get(
                    url=url,
                    request_timeout=(SSE_CONNECT_TIMEOUT, SSE_READ_TIMEOUT),
                    stream=True,
                )
                response.raise_for_status()
            except (ConnectionError, Timeout) as e:
                health.record_failure(f"{type(e).__name__}: {e}", reconnect_delay)
                reconnect_delay = self._sleep_before_reconnecting(reconnect_delay)
                continue
            except Exception as e:
                health.record_failure(
                    f"{type(e).__name__}: {e}", reconnect_delay, unexpected=True
                )
                reconnect_delay = self._sleep_before_reconnecting(reconnect_delay)
                continue

            if has_connected:
                logger.debug(f"Reconnected to SSE endpoint {url}")
            else:
                logger.info(f"Connected to SSE endpoint {url}")
                has_connected = True

            received_data: bool = False
            try:
                for line in response.iter_lines():
                    if not received_data:
                        received_data = True
                        health.record_healthy()
                        reconnect_delay = SSE_RECONNECT_INITIAL_DELAY

                    event: TEventModel | None = (
                        self._attempt_to_decode_sse_message_to_model(
                            line=line,
                            model_type=model_type,
                        )
                    )
                    if event is None:
                        continue

                    on_event(event)
                if received_data:
                    logger.info(f"SSE stream {url} ended, will re-establish connection")
                else:
                    health.record_failure(
                        "stream ended without delivering data", reconnect_delay
                    )
            except ChunkedEncodingError, ProtocolError:
                if received_data:
                    logger.info(
                        f"SSE stream {url} was interrupted, will re-establish connection"
                    )
                else:
                    health.record_failure(
                        "stream interrupted without delivering data", reconnect_delay
                    )
            except (ConnectionError, Timeout) as e:
                if _is_read_timeout(e):
                    # The connection stayed open for the whole read timeout, so
                    # this is a quiet stream rather than a failing one.
                    health.record_healthy()
                    reconnect_delay = SSE_RECONNECT_INITIAL_DELAY
                    logger.debug(
                        f"SSE stream {url} was idle for {SSE_READ_TIMEOUT:g}s, reconnecting"
                    )
                else:
                    health.record_failure(f"{type(e).__name__}: {e}", reconnect_delay)
            except Exception as e:
                health.record_failure(
                    f"error while listening to {model_type.__name__} events: "
                    f"{type(e).__name__}: {e}",
                    reconnect_delay,
                    unexpected=True,
                )
            finally:
                response.close()

            reconnect_delay = self._sleep_before_reconnecting(reconnect_delay)

    @staticmethod
    def _sleep_before_reconnecting(delay: float) -> float:
        """Wait before reconnecting and return the delay to use after that."""
        time.sleep(delay)
        return min(delay * 2, SSE_RECONNECT_MAX_DELAY)

    @staticmethod
    def _attempt_to_decode_sse_message_to_model(
        line: str, model_type: TEventModel
    ) -> TEventModel | None:
        if not line:
            return None

        decoded_line: str = line.decode("utf-8") if isinstance(line, bytes) else line
        # Skip empty lines and SSE comment lines
        if decoded_line.startswith(":"):
            return None

        # Parse SSE format: "data: {json_data}"
        if not decoded_line.startswith("data:"):
            return None

        try:
            data: str = decoded_line[5:].strip()
            event_data: dict = json.loads(data)
            event: TEventModel = model_type.model_validate(event_data)
            return event
        except JSONDecodeError, ValidationError:
            logger.exception(f"Failed to parse SSE event data: {decoded_line}")
            return None
        except Exception:
            logger.exception("Error processing SSE event")
            return None
