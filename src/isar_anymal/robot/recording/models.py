"""ANYmal-owned capture metadata and durable recording catalogs."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from pydantic import Field
from robot_interface.recording_models import (
    CameraRecording,
    RecordingModel,
    RecordingSession,
)


class CaptureMetadata(RecordingModel):
    source_codec: str = ""
    capture_mode: Literal["decoded-frames-to-h264"] | None = None
    width: int = 0
    height: int = 0
    rotation_degrees: int = 0
    last_frame_at: float | None = None


class CameraEvent(RecordingModel):
    type: Literal["started"]
    at: str


class DriverCameraRecording(CameraRecording):
    capture_metadata: CaptureMetadata = Field(default_factory=CaptureMetadata)
    finalization_started: bool = False
    segments: int = 0
    events: list[CameraEvent] = Field(default_factory=list)
    first_frame_at: str | None = None
    bytes: int | None = None
    finalization_mode: Literal["remuxed", "transcoded"] | None = None

    def apply_metadata(self, metadata: CaptureMetadata) -> None:
        for name in metadata.model_fields_set:
            setattr(self.capture_metadata, name, getattr(metadata, name))


class DriverRecordingSession(RecordingSession[DriverCameraRecording]):
    engine: str = "ISAR driver"
    mission_started_at: str | None = None


OpenSegment = Callable[[str, CaptureMetadata], Path]
UpdateCamera = Callable[[str, CaptureMetadata], None]
Capture = Callable[[asyncio.Event, OpenSegment, UpdateCamera], Awaitable[None]]
