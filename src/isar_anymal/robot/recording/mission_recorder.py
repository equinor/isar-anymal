"""Driver-owned background sessions with recoverable segments and private uploads."""

import asyncio
import hashlib
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from robot_interface.mission_recording import MissionRecorder
from robot_interface.recording_models import RecordingGap
from robot_interface.recording_publisher import RecordingPublisher

from isar_anymal.robot.recording.models import (
    CameraEvent,
    Capture,
    CaptureMetadata,
    DriverCameraRecording,
    DriverRecordingSession,
)
from isar_anymal.robot.recording.session_finalizer import SessionFinalizer

logger = logging.getLogger(__name__)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class AnymalMissionRecorder(MissionRecorder):
    """A driver's single background loop owns all metadata and media callbacks."""

    def __init__(
        self,
        capture: Capture,
        publisher: RecordingPublisher,
        *,
        directory: Path,
    ) -> None:
        self.capture = capture
        self.publisher = publisher
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, DriverRecordingSession] = {}
        self.workers: dict[str, tuple[asyncio.Event, asyncio.Task[None]]] = {}
        self.closing = False
        self.ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_loop, name="Mission recordings", daemon=True
        )
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError("Recording loop did not start")

    def start(self, mission_id: str) -> None:
        self.loop.call_soon_threadsafe(self._start_session, mission_id)

    def stop(self, mission_id: str, interrupted: bool = False) -> None:
        self.loop.call_soon_threadsafe(self._stop_session, mission_id, interrupted)

    def close(self) -> None:
        if not self.thread.is_alive():
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
        try:
            future.result(timeout=20)
        except Exception:  # Bounded recorder shutdown.
            logger.warning("Recording shutdown incomplete; durable segments retained")
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
        if not self.thread.is_alive():
            logger.info("Recording background thread stopped")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        for path in self.directory.glob("*/session.json"):
            session = DriverRecordingSession.model_validate_json(path.read_text())
            logger.info(
                "Recording session recovered mission_id=%s previous_status=%s interrupted=%s",
                session.run_id,
                session.status,
                not bool(session.ended_at),
            )
            if not session.ended_at:
                session.status = "Processing"
                session.ended_at = timestamp()
                session.gaps.append(
                    RecordingGap(
                        at=timestamp(),
                        reason="ISAR restarted; mission continuity unknown",
                    )
                )
            self.sessions[session.run_id] = session
            self._persist(session)
        self.maintenance = self.loop.create_task(self._maintain_sessions())
        self.ready.set()
        try:
            self.loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self.loop)
            for task in tasks:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self.loop.close()

    def _session_directory(self, session: DriverRecordingSession) -> Path:
        return self.directory / hashlib.sha256(session.run_id.encode()).hexdigest()

    def _persist(self, session: DriverRecordingSession) -> None:
        directory = self._session_directory(session)
        directory.mkdir(exist_ok=True)
        temporary = directory / "session.tmp"
        temporary.write_text(session.model_dump_json(by_alias=True, exclude_none=True))
        temporary.replace(directory / "session.json")

    async def _publish(self, session: DriverRecordingSession) -> None:
        await self.publisher.publish_session(session)

    def _start_session(self, mission_id: str) -> None:
        if self.closing or mission_id in self.workers:
            return
        existing = self.sessions.get(mission_id)
        if existing and existing.ended_at:
            return
        session = existing or DriverRecordingSession(
            run_id=mission_id,
            status="Starting",
            started_at=timestamp(),
            mission_started_at=timestamp(),
            cameras={},
        )
        self.sessions[mission_id] = session
        self._persist(session)
        stop = asyncio.Event()
        task = asyncio.create_task(self._capture_session(session, stop))
        self.workers[mission_id] = (stop, task)
        logger.info("Recording started mission_id=%s", mission_id)

    def _stop_session(self, mission_id: str, interrupted: bool) -> None:
        session = self.sessions.get(mission_id)
        if not session or session.ended_at:
            return
        session.ended_at = timestamp()
        if interrupted:
            session.gaps.append(
                RecordingGap(at=timestamp(), reason="Mission monitoring interrupted")
            )
        self._persist(session)
        if mission_id in self.workers:
            self.workers[mission_id][0].set()
        logger.info(
            "Recording stop requested mission_id=%s interrupted=%s",
            mission_id,
            interrupted,
        )

    async def _capture_session(
        self, session: DriverRecordingSession, stop: asyncio.Event
    ) -> None:
        def open_segment(camera: str, metadata: CaptureMetadata) -> Path:
            recording = session.cameras.setdefault(
                camera,
                DriverCameraRecording(
                    camera_id=camera,
                    key=hashlib.sha256(camera.encode()).hexdigest()[:20],
                    status="Recording",
                ),
            )
            recording.apply_metadata(metadata)
            recording.status = "Recording"
            recording.segments += 1
            recording.events.append(CameraEvent(type="started", at=timestamp()))
            logger.debug(
                "Recording segment opened mission_id=%s camera_id=%s segment=%s codec=%s",
                session.run_id,
                camera,
                recording.segments,
                recording.capture_metadata.source_codec,
            )
            session.status = "Recording"
            session.error = None
            self._persist(session)
            return (
                self._session_directory(session)
                / f"{recording.key}-{recording.segments:05}.mkv"
            )

        def update_camera(camera: str, metadata: CaptureMetadata) -> None:
            recording = session.cameras[camera]
            if recording.first_frame_at is None:
                recording.first_frame_at = timestamp()
                logger.info(
                    "First recording footage received mission_id=%s camera_id=%s",
                    session.run_id,
                    camera,
                )
            recording.apply_metadata(metadata)

        try:
            while not stop.is_set():
                try:
                    await self.capture(stop, open_segment, update_camera)
                except Exception as error:  # Retry capture failures.
                    reason = f"Native receiver failed ({type(error).__name__})"
                    repeated_failure = session.error == reason
                    session.status = "Reconnecting"
                    session.error = reason
                    session.gaps.append(RecordingGap(at=timestamp(), reason=reason))
                    self._persist(session)
                    if not repeated_failure:
                        logger.warning(
                            "Recording capture failed mission_id=%s error_type=%s; reconnecting",
                            session.run_id,
                            type(error).__name__,
                        )
                if not stop.is_set():
                    await asyncio.sleep(2)
            session.status = "Processing"
            session.ended_at = session.ended_at or timestamp()
            self._persist(session)
            await self._finalize(session)
        finally:
            self.workers.pop(session.run_id, None)

    async def _finalize(self, session: DriverRecordingSession) -> None:
        finalizer = SessionFinalizer(self.publisher, self._persist, self._publish)
        await finalizer.finalize_session(session, self._session_directory(session))

    async def _maintain_sessions(self) -> None:
        previous_failures: dict[str, str] = {}
        while True:
            for session in list(self.sessions.values()):
                try:
                    await self._maintain_session(session)
                    previous_failures.pop(session.run_id, None)
                except Exception as error:  # Retry publication and cleanup.
                    error_type = type(error).__name__
                    if previous_failures.get(session.run_id) != error_type:
                        logger.warning(
                            "Recording maintenance will retry mission_id=%s error_type=%s",
                            session.run_id,
                            error_type,
                        )
                    previous_failures[session.run_id] = error_type
            await asyncio.sleep(5)

    async def _maintain_session(self, session: DriverRecordingSession) -> None:
        if (
            session.status in ("Processing", "Failed", "Ready", "Expired")
            and session.ended_at
            and session.run_id not in self.workers
        ):
            await self._finalize(session)
            return
        await self._publish(session)

    async def _shutdown(self) -> None:
        self.closing = True
        active = list(self.workers.items())
        for mission_id, _ in active:
            self._stop_session(mission_id, True)
        if active:
            await asyncio.wait([worker[1][1] for worker in active], timeout=15)
        self.maintenance.cancel()
        await asyncio.gather(self.maintenance, return_exceptions=True)
