import json
import logging
import time
from threading import Thread
from typing import Callable, Optional, Type, TypeVar
from pydantic import ValidationError
from requests import JSONDecodeError, RequestException, Response
from requests.exceptions import ChunkedEncodingError
from urllib3.exceptions import ProtocolError

from isar_anymal.robot.api.request_handler import RequestHandler
from isar_anymal.robot.api.anymal_api.models import EventBaseModel

logger = logging.getLogger(__name__)

TEventModel = TypeVar("TEventModel", bound=EventBaseModel)


class SSEHandler:
    def __init__(self):
        self.request_handler: RequestHandler = RequestHandler()
        self.sse_listening_thread: Optional[Thread] = None

    def activate_sse_listening_thread(
        self,
        url: str,
        on_event: Callable[[TEventModel], None],
        model_type: Type[TEventModel],
    ) -> None:
        if self.sse_listening_thread is not None:
            if self.sse_listening_thread.is_alive():
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
                time.sleep(0.1)
                continue

            try:
                for line in response.iter_lines():
                    event: Optional[TEventModel] = (
                        self._attempt_to_decode_sse_message_to_model(
                            line=line,
                            model_type=model_type,
                        )
                    )
                    if event is None:
                        continue

                    on_event(event)
            except ChunkedEncodingError, ProtocolError:
                continue
            except RequestException, Exception:
                logger.exception(
                    f"An unexpected error occurred while listening to SSE event {model_type.__name__}, will attempt "
                    f"to re-establish connection"
                )
                time.sleep(0.1)
                continue
            finally:
                response.close()

    @staticmethod
    def _attempt_to_decode_sse_message_to_model(
        line: str, model_type: TEventModel
    ) -> Optional[TEventModel]:
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
