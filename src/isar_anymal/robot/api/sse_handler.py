import json
import logging
import time
from collections.abc import Callable
from threading import Thread
from typing import TypeVar

from pydantic import ValidationError
from requests import JSONDecodeError, RequestException, Response
from requests.exceptions import ChunkedEncodingError
from urllib3.exceptions import ProtocolError

from isar_anymal.robot.api.anymal_api.models import EventBaseModel
from isar_anymal.robot.api.request_handler import RequestHandler

logger = logging.getLogger(__name__)

TEventModel = TypeVar("TEventModel", bound=EventBaseModel)

# Delays between attempts to re-establish a dropped SSE stream. The delay
# doubles on every consecutive failure and resets once a stream is
# established, so a server that is down does not cause a hot reconnect loop.
SSE_RECONNECT_INITIAL_DELAY: float = 0.1
SSE_RECONNECT_MAX_DELAY: float = 30


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
        while True:
            try:
                response: Response = self.request_handler.get(
                    url=url,
                    request_timeout=None,
                    stream=True,
                )
                response.raise_for_status()
            except RequestException, Exception:
                logger.exception(
                    f"An unexpected error occurred while subscribing to SSE endpoint {url}"
                )
                reconnect_delay = self._sleep_before_reconnecting(reconnect_delay)
                continue

            logger.info(f"Connected to SSE endpoint {url}")
            reconnect_delay = SSE_RECONNECT_INITIAL_DELAY

            try:
                for line in response.iter_lines():
                    event: TEventModel | None = (
                        self._attempt_to_decode_sse_message_to_model(
                            line=line,
                            model_type=model_type,
                        )
                    )
                    if event is None:
                        continue

                    on_event(event)
                logger.info(f"SSE stream {url} ended, will re-establish connection")
            except ChunkedEncodingError, ProtocolError:
                logger.info(
                    f"SSE stream {url} was interrupted, will re-establish connection"
                )
            except RequestException, Exception:
                logger.exception(
                    f"An unexpected error occurred while listening to SSE event {model_type.__name__}, will attempt "
                    f"to re-establish connection"
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
