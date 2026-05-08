import json
import logging
import time
from typing import Optional

from requests import Response, RequestException
from uuid import uuid4

from isar_anymal.config import settings
from isar_anymal.robot.api.request_handler import RequestHandler

from threading import Thread

logger = logging.getLogger(__name__)


class MediaStream:
    def __init__(self, request_handler: RequestHandler) -> None:
        self.request_handler: RequestHandler = request_handler
        self.activate_stream_thread: Optional[Thread] = None

    def get_liveview_info(self) -> tuple[str, str]:
        # Get the liveview token, valid for 4 hours
        liveview_token_url: str = (
            f"{settings.SERVER_URL}/anymal-api/liveview/token?participant=isar-anymal-{uuid4()}"
        )
        liveview_response: Response = self.request_handler.get(
            url=liveview_token_url,
        ).json()["token"]
        return liveview_response["url"], liveview_response["token"]

    def robot_ready_to_stream(self):
        # Get the tracks
        liveview_sources_url = f"{settings.SERVER_URL}/anymal-api/liveview/sources?anymal={settings.ROBOT_NAME}"

        try:
            liveview_sources = self.request_handler.get(
                url=liveview_sources_url,
            ).json()
        except RequestException, Exception:
            logger.exception("Failed to retrieve liveview sources")
            return False

        for source in liveview_sources["sources"]:
            if source["frameId"] == "acoustic_camera":
                continue

            if source["state"] == 1:
                return True

        return False

    def start_streaming_and_continue_streaming_until_streams_go_offline(self):
        # Get the tracks
        liveview_sources_url = f"{settings.SERVER_URL}/anymal-api/liveview/sources?anymal={settings.ROBOT_NAME}"
        liveview_sources = self.request_handler.get(
            url=liveview_sources_url,
        ).json()

        sources = []
        for source in liveview_sources["sources"]:
            sources.append(source["frameId"])

        # Unmute
        tracks: dict = {"tracks": []}
        for source in sources:
            tracks["tracks"].append({"frameId": source})

        liveview_set_track_url = f"{settings.SERVER_URL}/anymal-api/liveview/tracks?anymal={settings.ROBOT_NAME}"
        while True:
            if not self.robot_ready_to_stream():
                break
            # Has to be call at least every 10s
            try:
                self.request_handler.post(
                    url=liveview_set_track_url,
                    headers={
                        "Authorization": f"Bearer {self.request_handler.get_token()}",
                        "accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    data=json.dumps(tracks),
                )
            except RequestException, Exception:
                logger.exception("Failed to keep media stream active, will retry...")

            time.sleep(3.0)

    def activate_stream(self):
        if (
            self.activate_stream_thread is not None
            and self.activate_stream_thread.is_alive()
        ):
            logger.info("Already activating stream")
            return

        if self.activate_stream_thread is not None:
            self.activate_stream_thread.join()
            self.activate_stream_thread = None

        self.activate_stream_thread = Thread(
            target=self.activate_when_active_and_keep_active,
            name="ISAR Anymal media stream activate",
            daemon=True,
        )
        self.activate_stream_thread.start()

    def activate_when_active_and_keep_active(self):
        seconds_to_wait_for_streams_to_become_active: float = 900  # 15 minutes
        start_time: float = time.time()
        while (time.time() - start_time) < seconds_to_wait_for_streams_to_become_active:
            if self.robot_ready_to_stream():
                break

            time.sleep(5)

        if not self.robot_ready_to_stream():
            logger.info(
                "Robot streams are not available after waiting for them to become active"
            )
            return

        self.start_streaming_and_continue_streaming_until_streams_go_offline()

    def is_active(self):
        if self.activate_stream_thread is None:
            return False
        return self.activate_stream_thread.is_alive()
