import asyncio
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from isar_anymal.robot.recording.livekit_capture import _LiveKitRecorder, _TrackEncoder
from isar_anymal.robot.recording.mission_recorder import AnymalMissionRecorder
from isar_anymal.robot.recording.models import (
    CaptureMetadata,
    DriverCameraRecording,
    DriverRecordingSession,
)
from isar_anymal.robot.recording.session_finalizer import SessionFinalizer


def test_cancellation_waits_for_native_encoding_to_finish():
    async def verify():
        encoder = object.__new__(_TrackEncoder)
        encoder._convert_frame = Mock(return_value="frame")
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def encode_frame(_frame):
            started.set()
            release.wait(5)
            finished.set()

        encoder._encode_frame = encode_frame
        task = asyncio.create_task(encoder.encode_event(Mock()))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(verify())


def test_frame_monitor_allows_startup_then_detects_missing_and_stalled_frames():
    async def verify():
        with patch("livekit.rtc.Room"):
            recorder = _LiveKitRecorder(Mock(), asyncio.Event(), Mock(), Mock())
        with patch(
            "isar_anymal.robot.recording.livekit_capture.time.monotonic",
            return_value=100,
        ):
            recorder._check_frame_progress(80)
            with pytest.raises(RuntimeError, match="frames stalled"):
                recorder._check_frame_progress(60)
            recorder.observed = {"front": 99, "rear": 80}
            with pytest.raises(RuntimeError, match="frames stalled"):
                recorder._check_frame_progress(60)
            recorder.observed["rear"] = 99
            recorder._check_frame_progress(60)

    asyncio.run(verify())


@pytest.fixture
def recorder(tmp_path):
    recorder = AnymalMissionRecorder.__new__(AnymalMissionRecorder)
    recorder.directory = tmp_path
    recorder.workers = {}
    recorder.publisher = Mock()
    recorder._finalize = AsyncMock()
    recorder._publish = AsyncMock()
    return recorder


def test_capture_persists_recoverable_catalog(recorder):
    session = DriverRecordingSession(run_id="mission", status="Starting", cameras={})

    async def capture(stop, open_segment, update_camera):
        assert (
            open_segment("front", CaptureMetadata(source_codec="H264")).suffix == ".mkv"
        )
        update_camera("front", CaptureMetadata(last_frame_at=123.5))
        stop.set()

    recorder.capture = capture
    asyncio.run(recorder._capture_session(session, asyncio.Event()))

    recovered = DriverRecordingSession.model_validate_json(
        (recorder._session_directory(session) / "session.json").read_text()
    )
    assert recovered == session
    assert recovered.status == "Processing"
    assert recovered.ended_at is not None
    assert recovered.cameras["front"].capture_metadata.source_codec == "H264"
    assert recovered.cameras["front"].capture_metadata.last_frame_at == 123.5
    assert recovered.cameras["front"].segments == 1
    recorder._finalize.assert_awaited_once_with(session)


@pytest.fixture
def finalization(tmp_path, mocker):
    def write_video(source, output, **options):
        output.write_bytes(b"video")

    for operation in ("convert_segment", "concatenate_segments"):
        mocker.patch(
            f"isar_anymal.robot.recording.session_finalizer.{operation}",
            new=AsyncMock(side_effect=write_video),
        )
    mocker.patch(
        "isar_anymal.robot.recording.session_finalizer.validate_video", new=AsyncMock()
    )
    (tmp_path / "session.json").write_text("{}")
    (tmp_path / "front-00001.mkv").write_bytes(b"footage")
    session = DriverRecordingSession(
        run_id="mission",
        status="Processing",
        cameras={
            "front": DriverCameraRecording(
                camera_id="front",
                key="front",
                status="Processing",
                capture_metadata=CaptureMetadata(source_codec="H264"),
            )
        },
    )
    publisher = Mock(publish_video=AsyncMock(return_value="opaque-reference"))
    return SessionFinalizer(publisher, Mock(), AsyncMock()), session, tmp_path


def test_success_removes_footage_before_publication(finalization):
    finalizer, session, directory = finalization

    async def publish(document):
        assert document.status == "Ready"
        assert not (directory / "front-00001.mkv").exists()

    finalizer.publish.side_effect = publish
    asyncio.run(finalizer.finalize_session(session, directory))

    assert list(directory.iterdir()) == [directory / "session.json"]
    assert session.cameras["front"].artifact_reference == "opaque-reference"
    finalizer.publisher.publish_video.assert_awaited_once()


def test_failed_upload_expires_only_failed_camera_and_removes_all_footage(finalization):
    finalizer, session, directory = finalization
    session.cameras["arm"] = DriverCameraRecording(
        camera_id="arm",
        key="arm",
        status="Processing",
        capture_metadata=CaptureMetadata(rotation_degrees=90),
    )
    (directory / "arm-00001.mkv").write_bytes(b"footage")
    finalizer.publisher.publish_video.side_effect = [OSError(), "arm-ref", "front-ref"]

    asyncio.run(finalizer.finalize_session(session, directory))
    assert session.status == "Expired"
    assert session.cameras["front"].status == "Expired"
    assert "upload" in session.cameras["front"].error
    assert session.cameras["arm"].status == "Ready"
    assert list(directory.iterdir()) == [directory / "session.json"]

    asyncio.run(finalizer.finalize_session(session, directory))
    assert session.status == "Expired"
    assert finalizer.publisher.publish_video.await_count == 2
    assert list(directory.iterdir()) == [directory / "session.json"]


@pytest.mark.parametrize("failure_stage", ["publication", "cleanup"])
@pytest.mark.parametrize("upload_fails", [False, True])
def test_maintenance_retries_publication_and_cleanup_after_restart(
    finalization, recorder, mocker, failure_stage, upload_fails
):
    finalizer, session, directory = finalization
    directory = recorder._session_directory(session)
    directory.mkdir()
    (directory / "front-00001.mkv").write_bytes(b"footage")
    session.ended_at = datetime.now(UTC).isoformat()
    finalizer.persist = recorder._persist
    if upload_fails:
        finalizer.publisher.publish_video.side_effect = OSError()
    recorder._finalize = lambda document: finalizer.finalize_session(
        document, directory
    )
    cleanup = mocker.patch.object(
        finalizer, "_remove_local_footage", wraps=finalizer._remove_local_footage
    )
    if failure_stage == "publication":
        finalizer.publish.side_effect = OSError()
    else:
        cleanup.side_effect = PermissionError()
    with pytest.raises(OSError):
        asyncio.run(recorder._maintain_session(session))
    assert (directory / "front-00001.mkv").exists() == (failure_stage == "cleanup")

    recovered = DriverRecordingSession.model_validate_json(
        (directory / "session.json").read_text()
    )
    assert recovered.status == ("Expired" if upload_fails else "Ready")
    finalizer.publish.side_effect = None
    cleanup.side_effect = None
    asyncio.run(recorder._maintain_session(recovered))
    finalizer.publisher.publish_video.assert_awaited_once()
    assert finalizer.publish.await_count == (2 if failure_stage == "publication" else 1)
    assert list(directory.iterdir()) == [directory / "session.json"]


@pytest.mark.parametrize("active", [False, True])
def test_maintenance_only_finalizes_inactive_sessions(recorder, active):
    session = DriverRecordingSession(
        run_id="mission",
        status="Processing",
        cameras={},
        ended_at=(datetime.now(UTC) - timedelta(days=8)).isoformat(),
    )
    recorder._persist(session)
    directory = recorder._session_directory(session)
    footage = directory / "segment.mkv"
    footage.write_bytes(b"footage")
    if active:
        recorder.workers["mission"] = Mock()

    asyncio.run(recorder._maintain_session(session))

    assert footage.exists()
    assert session.status == "Processing"
    assert (directory / "session.json").exists()
    assert recorder._finalize.await_count == int(not active)
