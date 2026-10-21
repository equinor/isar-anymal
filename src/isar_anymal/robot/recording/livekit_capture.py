"""ANYmal viewer capture; credentials and camera activation stay in the driver."""

import asyncio
import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import numpy as np
from livekit import rtc
from robot_interface.models.robots.media import MediaConfig

from isar_anymal.robot.recording.models import (
    CaptureMetadata,
    OpenSegment,
    UpdateCamera,
)

CAMERA_KEEPALIVE_INTERVAL = 20
ROOM_CONNECT_TIMEOUT = 30
FIRST_FRAME_TIMEOUT = 30
FRAME_STALL_TIMEOUT = 15
CAPTURE_POLL_INTERVAL = 0.2
FRAME_TIME_BASE = Fraction(1, 1_000_000)


class _TrackEncoder:
    """Own one track's Matroska output and timestamp-preserving H.264 encoder."""

    def __init__(self, path: Path, event: Any) -> None:
        """Open a recoverable segment using the first frame's dimensions."""
        self.first_timestamp = event.timestamp_us
        self.output = av.open(
            str(path),
            "w",
            format="matroska",
            options={"flush_packets": "1", "cluster_time_limit": "1000"},
        )
        self.encoder = self._configure_encoder(event.frame)

    def _configure_encoder(self, frame: Any) -> Any:
        """Configure low-latency H.264 while retaining microsecond timestamps."""
        encoder = self.output.add_stream("libx264", rate=30)
        encoder.width, encoder.height = frame.width, frame.height
        encoder.pix_fmt = "yuv420p"
        encoder.time_base = FRAME_TIME_BASE
        encoder.options = {"preset": "veryfast", "crf": "23", "tune": "zerolatency"}
        return encoder

    def _convert_frame(self, event: Any) -> Any:
        """Convert LiveKit RGBA pixels to a frame timed relative to segment start."""
        pixels = np.frombuffer(event.frame.data, dtype=np.uint8).reshape(
            event.frame.height, event.frame.width, 4
        )
        frame = av.VideoFrame.from_ndarray(pixels, format="rgba")
        frame.pts = event.timestamp_us - self.first_timestamp
        frame.time_base = FRAME_TIME_BASE
        return frame

    def _encode_frame(self, frame: Any) -> None:
        """Encode and mux on a worker thread without blocking camera keepalives."""
        for packet in self.encoder.encode(frame):
            self.output.mux(packet)

    async def encode_event(self, event: Any) -> None:
        """Finish in-flight encoding before allowing cancellation to close output."""
        frame = self._convert_frame(event)
        encoding = asyncio.create_task(asyncio.to_thread(self._encode_frame, frame))
        try:
            await asyncio.shield(encoding)
        except asyncio.CancelledError:
            await encoding
            raise

    def close(self) -> None:
        """Flush delayed encoder packets before closing the Matroska segment."""
        for packet in self.encoder.encode():
            self.output.mux(packet)
        self.output.close()


class _LiveKitRecorder:
    """Coordinate camera tracks and room lifecycle on the recording asyncio loop."""

    def __init__(
        self,
        generate_config: Callable[[], MediaConfig],
        stop: asyncio.Event,
        open_segment: OpenSegment,
        update_camera: UpdateCamera,
    ) -> None:
        """Create isolated capture state and register LiveKit event callbacks."""
        self.rtc = rtc
        self.generate_config = generate_config
        self.stop = stop
        self.open_segment = open_segment
        self.update_camera = update_camera
        self.room = rtc.Room()
        self.tasks: set[asyncio.Task] = set()
        self.failure: asyncio.Future[Exception] = (
            asyncio.get_running_loop().create_future()
        )
        self.observed: dict[str, float] = {}
        self._register_room_callbacks()

    def _register_room_callbacks(self) -> None:
        """Subscribe to video arrivals, track loss and room disconnection."""
        self.room.on("track_subscribed", self._start_video_track)
        self.room.on("track_unsubscribed", self._handle_track_unsubscribed)
        self.room.on("disconnected", self._handle_disconnection)

    def _report_failure(self, error: Exception) -> None:
        """Retain the first capture failure for the lifecycle monitor."""
        if not self.failure.done():
            self.failure.set_result(error)

    def _start_video_track(
        self, track: Any, publication: Any, participant: Any
    ) -> None:
        """Start a recording task for each subscribed video track."""
        if track.kind == self.rtc.TrackKind.KIND_VIDEO:
            task = asyncio.create_task(
                self._record_track(track, publication, participant)
            )
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    def _handle_track_unsubscribed(
        self, track: Any, _publication: Any, _participant: Any
    ) -> None:
        """Treat video track loss as a failure requiring a fresh capture session."""
        if track.kind == self.rtc.TrackKind.KIND_VIDEO:
            self._report_failure(RuntimeError("LiveKit camera track unsubscribed"))

    def _handle_disconnection(self, *_args: Any) -> None:
        """Notify the monitor when the viewer room disconnects."""
        self._report_failure(RuntimeError("LiveKit disconnected"))

    def _open_track_encoder(
        self, camera: str, publication: Any, event: Any
    ) -> _TrackEncoder:
        """Allocate footage with source metadata when the first frame arrives."""
        path = self.open_segment(
            camera,
            CaptureMetadata(
                source_codec=publication.mime_type,
                capture_mode="decoded-frames-to-h264",
                width=event.frame.width,
                height=event.frame.height,
            ),
        )
        return _TrackEncoder(path, event)

    def _update_frame_arrival(self, camera: str) -> None:
        """Update stall detection and persisted camera metadata after encoding."""
        self.observed[camera] = time.monotonic()
        self.update_camera(camera, CaptureMetadata(last_frame_at=time.time()))

    async def _record_track(
        self, track: Any, publication: Any, participant: Any
    ) -> None:
        """Encode bounded LiveKit frames and release the stream on exit."""
        camera = f"{participant.identity}/{publication.name or publication.source}"
        self.observed[camera] = time.monotonic()
        stream = self.rtc.VideoStream(
            track, capacity=2, format=self.rtc.VideoBufferType.RGBA
        )
        encoder = None
        try:
            async for event in stream:
                if self.stop.is_set():
                    break
                if encoder is None:
                    encoder = self._open_track_encoder(camera, publication, event)
                await encoder.encode_event(event)
                self._update_frame_arrival(camera)
        except Exception as error:
            self._report_failure(error)
        finally:
            await stream.aclose()
            if encoder is not None:
                encoder.close()

    async def _keep_cameras_active(self) -> None:
        """Refresh viewer configuration to renew camera activation periodically."""
        while True:
            await asyncio.sleep(CAMERA_KEEPALIVE_INTERVAL)
            await asyncio.to_thread(self.generate_config)

    def _check_frame_progress(self, connected_at: float) -> None:
        """Allow startup grace, then reject missing or stalled camera frames."""
        now = time.monotonic()
        if now - connected_at > FIRST_FRAME_TIMEOUT and (
            not self.observed
            or any(now - at > FRAME_STALL_TIMEOUT for at in self.observed.values())
        ):
            raise RuntimeError("LiveKit camera frames stalled")

    async def _monitor_capture(self, keepalive: asyncio.Task) -> None:
        """Watch capture failures, activation and frame progress until mission stop."""
        connected_at = time.monotonic()
        while not self.stop.is_set():
            if self.failure.done():
                raise self.failure.result()
            if keepalive.done():
                keepalive.result()
            self._check_frame_progress(connected_at)
            await asyncio.sleep(CAPTURE_POLL_INTERVAL)

    async def _close_capture(self, keepalive: asyncio.Task) -> None:
        """Drain encoding tasks before disconnecting the viewer room."""
        tasks = [keepalive, *self.tasks]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.room.disconnect()

    async def capture(self) -> None:
        """Connect with approved viewer credentials and own the capture lifecycle."""
        config = await asyncio.to_thread(self.generate_config)
        keepalive = asyncio.create_task(self._keep_cameras_active())
        try:
            await asyncio.wait_for(
                self.room.connect(config.url, config.token), ROOM_CONNECT_TIMEOUT
            )
            await self._monitor_capture(keepalive)
        finally:
            await self._close_capture(keepalive)


async def capture_livekit(
    generate_config: Callable[[], MediaConfig],
    stop: asyncio.Event,
    open_segment: OpenSegment,
    update_camera: UpdateCamera,
) -> None:
    """Record approved ANYmal camera tracks through the driver's viewer connection."""
    recorder = _LiveKitRecorder(generate_config, stop, open_segment, update_camera)
    await recorder.capture()
