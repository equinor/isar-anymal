import logging
import time
from threading import Lock, Thread
from uuid import uuid4

from requests import RequestException, Response

from isar_anymal.config import settings
from isar_anymal.robot.api.request_handler import RequestHandler

logger = logging.getLogger(__name__)


class MediaStream:
    RECOVERY_TIMEOUT = 900.0
    INITIAL_RETRY_DELAY = 5.0
    MAX_RETRY_DELAY = 30.0
    KEEPALIVE_INTERVAL = 3.0

    def __init__(self, request_handler: RequestHandler) -> None:
        self.request_handler: RequestHandler = request_handler
        self.activate_stream_thread: Thread | None = None
        self._activation_lock = Lock()

    def get_liveview_info(self) -> tuple[str, str]:
        # Get the liveview token, valid for 4 hours
        liveview_token_url: str = (
            f"{settings.SERVER_URL}/anymal-api/liveview/token?participant=isar-anymal-{uuid4()}"
        )
        liveview_response: Response = self.request_handler.get(
            url=liveview_token_url,
        ).json()["token"]
        return liveview_response["url"], liveview_response["token"]

    def activate_when_active_and_keep_active(self) -> None:
        liveview_sources_url = f"{settings.SERVER_URL}/anymal-api/liveview/sources?anymal={settings.ROBOT_NAME}"
        liveview_set_track_url = f"{settings.SERVER_URL}/anymal-api/liveview/tracks?anymal={settings.ROBOT_NAME}"
        deadline = time.monotonic() + self.RECOVERY_TIMEOUT
        retry_delay = self.INITIAL_RETRY_DELAY
        streaming = False
        request_error_logged = False
        logger.info("Waiting up to %.0fs for media streams", self.RECOVERY_TIMEOUT)

        while (remaining := deadline - time.monotonic()) > 0:
            try:
                sources = self.request_handler.get(
                    url=liveview_sources_url,
                    request_timeout=min(settings.API_REQUEST_TIMEOUT, remaining),
                ).json()["sources"]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                if any(
                    source["frameId"] != "acoustic_camera" and source["state"] == 1
                    for source in sources
                ):
                    # Refresh tracks on every attempt, including after reconnecting.
                    tracks = {
                        "tracks": [{"frameId": source["frameId"]} for source in sources]
                    }
                    self.request_handler.post(
                        url=liveview_set_track_url,
                        json_body=tracks,
                        request_timeout=min(settings.API_REQUEST_TIMEOUT, remaining),
                    )
                    if not streaming:
                        logger.info("Media stream keepalives active")
                    streaming = True
                    request_error_logged = False
                    # Readiness alone must not extend a failing keepalive's lifetime.
                    deadline = time.monotonic() + self.RECOVERY_TIMEOUT
                    retry_delay = self.INITIAL_RETRY_DELAY
                    time.sleep(self.KEEPALIVE_INTERVAL)
                    continue
            except RequestException as error:
                if not request_error_logged:
                    logger.warning("Media stream request failed; retrying: %s", error)
                    request_error_logged = True

            if streaming:
                logger.info("Media streams unavailable; attempting bounded recovery")
            streaming = False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(retry_delay, remaining))
            retry_delay = min(retry_delay * 2, self.MAX_RETRY_DELAY)

        logger.info(
            "Media stream recovery expired after %.0fs without a successful "
            "keepalive; a new media config request can restart it",
            self.RECOVERY_TIMEOUT,
        )

    def activate_stream(self) -> None:
        with self._activation_lock:
            if (
                self.activate_stream_thread is not None
                and self.activate_stream_thread.is_alive()
            ):
                return

            if self.activate_stream_thread is not None:
                self.activate_stream_thread.join()

            self.activate_stream_thread = Thread(
                target=self.activate_when_active_and_keep_active,
                name="ISAR Anymal media stream activate",
                daemon=True,
            )
            self.activate_stream_thread.start()

    def is_active(self) -> bool:
        with self._activation_lock:
            return (
                self.activate_stream_thread is not None
                and self.activate_stream_thread.is_alive()
            )
