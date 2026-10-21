"""Finalize durable camera segments and publish private mission recordings."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from robot_interface.recording_models import RecordingGap
from robot_interface.recording_publisher import RecordingArtifact, RecordingPublisher

from isar_anymal.robot.recording.ffmpeg import (
    concatenate_segments,
    convert_segment,
    validate_video,
)
from isar_anymal.robot.recording.models import (
    DriverCameraRecording,
    DriverRecordingSession,
)

logger = logging.getLogger(__name__)


class SessionFinalizer:
    """Own media finalization while the recorder owns session persistence."""

    def __init__(
        self,
        publisher: RecordingPublisher,
        persist: Callable[[DriverRecordingSession], None],
        publish: Callable[[DriverRecordingSession], Awaitable[None]],
    ) -> None:
        self.publisher = publisher
        self.persist = persist
        self.publish = publish

    async def finalize_session(
        self, session: DriverRecordingSession, directory: Path
    ) -> None:
        """Attempt each camera once, persist terminal results, and remove local media."""
        previous_status = session.status
        for camera in session.cameras.values():
            await self._finalize_camera_recording(session, camera, directory)
        session.status = (
            "Ready"
            if session.cameras
            and all(camera.status == "Ready" for camera in session.cameras.values())
            else "Expired"
        )
        self.persist(session)
        self._remove_local_footage(directory)
        await self.publish(session)
        if session.status != previous_status:
            logger.info(
                "Recording session published mission_id=%s status=%s ready_cameras=%s total_cameras=%s",
                session.run_id,
                session.status,
                sum(camera.status == "Ready" for camera in session.cameras.values()),
                len(session.cameras),
            )

    async def _finalize_camera_recording(
        self,
        session: DriverRecordingSession,
        camera: DriverCameraRecording,
        directory: Path,
    ) -> None:
        if camera.status in ("Ready", "Expired"):
            return
        if camera.finalization_started:
            camera.status = "Expired"
            camera.error = "Finalization interrupted; local footage discarded"
            self.persist(session)
            return
        started = monotonic()
        stage = "conversion"
        camera.finalization_started = True
        camera.status = "Processing"
        self.persist(session)
        try:
            passthrough = self._can_remux(camera)
            logger.debug(
                "Camera recording processing mission_id=%s camera_id=%s mode=%s",
                session.run_id,
                camera.camera_id,
                "remuxed" if passthrough else "transcoded",
            )
            converted = await self._convert_segments(
                session, camera, directory, passthrough
            )
            stage = "concatenation"
            final = await self._combine_segments(converted, directory, camera.key)
            stage = "upload"
            reference = await self.publisher.publish_video(
                session.run_id,
                RecordingArtifact(
                    camera_id=camera.camera_id,
                    artifact_id=camera.key,
                    path=final,
                    content_type="video/mp4",
                ),
            )
            camera.status = "Ready"
            camera.artifact_reference = reference
            camera.bytes = final.stat().st_size
            camera.finalization_mode = "remuxed" if passthrough else "transcoded"
            camera.error = None
            logger.info(
                "Camera recording ready mission_id=%s camera_id=%s mode=%s bytes=%s elapsed_seconds=%.2f",
                session.run_id,
                camera.camera_id,
                camera.finalization_mode,
                camera.bytes,
                monotonic() - started,
            )
        except Exception as error:  # Best-effort finalization.
            camera.status = "Expired"
            camera.error = f"Finalization failed during {stage} ({type(error).__name__}); local footage discarded"
            logger.warning(
                "Camera recording expired; discarding local footage mission_id=%s camera_id=%s stage=%s error_type=%s",
                session.run_id,
                camera.camera_id,
                stage,
                type(error).__name__,
            )
        self.persist(session)

    @staticmethod
    def _can_remux(camera: DriverCameraRecording) -> bool:
        metadata = camera.capture_metadata
        return not metadata.rotation_degrees % 360 and (
            metadata.source_codec.upper() in ("H264", "VIDEO/H264")
            or metadata.capture_mode == "decoded-frames-to-h264"
        )

    async def _convert_segments(
        self,
        session: DriverRecordingSession,
        camera: DriverCameraRecording,
        directory: Path,
        passthrough: bool,
    ) -> list[Path]:
        converted = []
        for segment in sorted(directory.glob(f"{camera.key}-*.mkv")):
            if not segment.stat().st_size:
                continue
            output = segment.with_suffix(".mp4")
            try:
                await convert_segment(
                    segment,
                    output,
                    passthrough=passthrough,
                    rotation_degrees=camera.capture_metadata.rotation_degrees % 360,
                )
                await validate_video(output)
                converted.append(output)
            except RuntimeError:
                self._record_segment_gap(session, segment)
        if not converted:
            raise RuntimeError("No decodable footage")
        return converted

    @staticmethod
    def _record_segment_gap(session: DriverRecordingSession, segment: Path) -> None:
        reason = f"Undecodable segment: {segment.name}"
        if any(gap.reason == reason for gap in session.gaps):
            return
        session.gaps.append(
            RecordingGap(at=datetime.now(UTC).isoformat(), reason=reason)
        )
        logger.warning(
            "Undecodable recording segment mission_id=%s segment=%s",
            session.run_id,
            segment.name,
        )

    @staticmethod
    async def _combine_segments(
        converted: list[Path], directory: Path, camera_key: str
    ) -> Path:
        manifest = directory / f"{camera_key}.txt"
        manifest.write_text("".join(f"file '{path.name}'\n" for path in converted))
        final = directory / f"{camera_key}.mp4"
        await concatenate_segments(manifest, final)
        await validate_video(final)
        return final

    @staticmethod
    def _remove_local_footage(directory: Path) -> None:
        for path in directory.iterdir():
            if path.name != "session.json":
                path.unlink()
