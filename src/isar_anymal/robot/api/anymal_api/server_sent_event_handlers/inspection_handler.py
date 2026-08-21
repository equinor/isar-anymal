import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from alitra import Frame, Orientation, Pose, Position, Transform
from pydantic import ValidationError
from requests import RequestException
from requests.models import Response
from robot_interface.models.exceptions.robot_exceptions import (
    RobotRetrieveInspectionException,
)
from robot_interface.models.inspection.inspection import (
    AcousticMeasurement,
    AcousticMeasurementMetadata,
    AudioMetadata,
    CO2Measurement,
    GasMeasurementMetadata,
    Image,
    ImageMetadata,
    Inspection,
    InspectionMetadata,
    InspectionValue,
    ThermalVideoMetadata,
    VideoMetadata,
)
from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.task import TASKS

from isar_anymal.config import settings
from isar_anymal.robot.api.anymal_api.enums import (
    InspectionInterpretationType,
    InspectionMeasurementType,
)
from isar_anymal.robot.api.anymal_api.models import (
    ConcentrationMeasurementDto,
    InspectionEventDto,
    LeakDetectionInterpretationDto,
    VideoMeasurementDto,
)
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.utilities import (
    import_transform_from_map_file,
)
from isar_anymal.robot.api.request_handler import RequestHandler
from isar_anymal.robot.api.sse_handler import SSEHandler

logger = logging.getLogger(__name__)


class InspectionHandler:
    def __init__(self) -> None:
        self.inspections_queue: deque[tuple[TASKS, str]] = deque(maxlen=1000)
        self.missions_inspection_queue: deque[tuple[str, Mission]] = deque(maxlen=100)
        self.transform: Transform = import_transform_from_map_file()
        self.request_handler: RequestHandler = RequestHandler()

        self.inspection_sse_handler: SSEHandler = SSEHandler()

    def process_inspection_callback(
        self,
        event: InspectionEventDto,
        final_callback: Callable[[Inspection, Mission], None],
    ) -> None:
        _process_inspection_event(
            event=event,
            inspections_queue=self.inspections_queue,
            missions_inspection_queue=self.missions_inspection_queue,
            transform=self.transform,
            final_callback=final_callback,
            request_handler=self.request_handler,
        )

    def register_process_inspection_callback(
        self, final_callback: Callable[[Inspection, Mission], None]
    ) -> None:
        url: str = (
            f"{settings.SERVER_URL}/anymal-api/events/inspection?anymal={settings.ROBOT_NAME}"
        )

        def on_event(event: InspectionEventDto) -> None:
            self.process_inspection_callback(event=event, final_callback=final_callback)

        self.inspection_sse_handler.activate_sse_listening_thread(
            url=url,
            on_event=on_event,
            model_type=InspectionEventDto,
        )


def _process_inspection_event(
    event: InspectionEventDto,
    inspections_queue: deque[tuple[TASKS, str]],
    missions_inspection_queue: deque[tuple[str, Mission]],
    transform: Transform,
    final_callback: Callable[[Inspection, Mission], None],
    request_handler: RequestHandler,
) -> None:
    """This function gathers raw data and its metadata, then passes it back to ISAR. Already
    interpreted data is available in the event, but not used.
    """

    if event.measurement.type == InspectionMeasurementType.IMT_CONCENTRATION_MONITORING:
        return
    logger.info(event)

    if event.measurement.sensor_pose.frame_id == "invalid":
        error_message: str = (
            f"Received invalid, empty robot pose for inspection event with asset ID {event.asset_id} and "
            f"mission run id {event.metadata.mission_run_id}"
        )
        logger.error(error_message)
        logger.error(f"The event was: {event}")

        return

    task: TASKS
    has_inspection: bool = False
    for inspection_tuple in inspections_queue:
        task, anymal_mission_task_name = inspection_tuple
        if anymal_mission_task_name == event.asset_id:
            has_inspection = True
            break
    if not has_inspection:
        logger.warning(
            f"INSPECTION UPLOADING: failed to find scheduled task with ID {event.task_run_uid}"
        )
        return

    mission: Mission | None = None
    for mission_run_id, _mission in missions_inspection_queue:
        if mission_run_id == event.metadata.mission_run_id:
            mission = _mission
    if not mission:
        logger.warning(
            f"INSPECTION UPLOADING: failed to find scheduled mission with missionRunID {event.metadata.mission_run_id}"
        )
        return

    try:
        inspections_queue.remove(inspection_tuple)
    except ValueError:
        logger.exception("Failed to remove inspection from queue")
        return

    inspection: Inspection
    robot_pose: Pose = _extract_robot_pose(event=event, transform=transform)
    target_position: Position = _extract_target_position(task, robot_pose)
    metadata_type: type[InspectionMetadata]
    inspection_type: type[Inspection]

    try:
        if _is_acoustic_inspection(event):
            inspection_type = AcousticMeasurement
            inspection = _process_acoustic_inspection(
                event=event,
                request_handler=request_handler,
                robot_pose=robot_pose,
                target_position=target_position,
                task=task,
            )

        elif _is_blob_inspection(event):
            (
                file_bytes,
                metadata_type,
                file_type,
                inspection_type,
                video_duration,
            ) = _process_inspection_blob(event=event, request_handler=request_handler)

            if file_type.find(",") >= 0:
                file_type = file_type[file_type.find(",") + 1 : len(file_type)]
            inspection = _create_blob_inspection(
                metadata_type=metadata_type,
                inspection_type=inspection_type,
                robot_pose=robot_pose,
                target_position=target_position,
                file_type=file_type,
                task=task,
                file_bytes=file_bytes,
                video_duration=video_duration,
            )

        elif _is_value_inspection(event):
            value, unit, metadata_type, inspection_type = _process_inspection_value(
                event
            )

            inspection = _create_value_inspection(
                task=task,
                value=value,
                unit=unit,
                metadata_type=metadata_type,
                inspection_type=inspection_type,
                robot_pose=robot_pose,
                target_position=target_position,
            )
        else:
            raise RobotRetrieveInspectionException(
                f"Unsupported inspection event type {event.measurement.type} received"
            )
    except RobotRetrieveInspectionException as e:
        logger.warning(
            f"Unknown callback event for asset {event.asset_id}. {e.error_description}"
        )
        return

    logger.info(
        f"Processed inspection event of inspection type {inspection_type} for tag ID {task.tag_id}"
    )
    final_callback(inspection, mission)


def _process_inspection_value(
    event: InspectionEventDto,
) -> tuple[float, str, type[InspectionMetadata], type[InspectionValue]]:
    value: float
    unit: str
    metadata_type: type[InspectionMetadata]
    inspection_type: type[InspectionValue]

    if event.measurement.type == InspectionMeasurementType.IMT_CONCENTRATION:
        try:
            concentration_measurement = ConcentrationMeasurementDto.model_validate(
                event.measurement.data
            )
        except ValidationError as e:
            raise RobotRetrieveInspectionException(
                "Failed to parse concentration measurement data of type "
                f"{type(event.measurement.data).__name__}"
            ) from e

        # The API specification says value is optional and as such the model is set with
        # an optional value. However, we do require the value to be present. Thus, a
        # check has been added here, and hopefully it can be removed in the future if
        # the specification is changed to be required.
        if concentration_measurement.value is None:
            raise RobotRetrieveInspectionException(
                "Concentration measurement did not contain a value"
            )

        value = (
            concentration_measurement.value / 10000
        )  # Convert ppm to volume percentage
        unit = "% v/v"
        metadata_type = GasMeasurementMetadata
        inspection_type = CO2Measurement

    else:
        raise RobotRetrieveInspectionException(
            f"Unsupported inspection value type {event.measurement.type} received"
        )

    return value, unit, metadata_type, inspection_type


def _process_inspection_blob(
    event: InspectionEventDto, request_handler: RequestHandler
) -> tuple[bytes, type[InspectionMetadata], str, type[Inspection], int | None]:
    file_bytes: bytes
    metadata_type: type[InspectionMetadata]
    file_type: str
    inspection_type: type[Inspection]
    video_duration: int | None = None

    # if event.measurement.type == InspectionMeasurementType.IMT_THERMAL:
    #     metadata_type = ThermalImageMetadata
    #     inspection_type = ThermalImage

    #     thermal_object: AnymalImage = event.measurement.thermal
    #     file_bytes = thermal_object.thermal_image.image.data
    #     file_type = thermal_object.thermal_image.image.encoding
    #     # We can also gather the 'gain' and 'offset' from the thermal_image metadata

    if event.measurement.type == InspectionMeasurementType.IMT_VISUAL:
        metadata_type = ImageMetadata
        inspection_type = Image
        file_bytes, file_type = _fetch_blob_via_data_navigator(
            task_run_uid=event.task_run_uid, request_handler=request_handler
        )

    # elif event.measurement.type == InspectionMeasurementType.IMT_VIDEO:
    #     metadata_type = VideoMetadata
    #     inspection_type = Video

    #     video_object: AnymalVideo = event.measurement.video
    #     file_bytes = video_object.video_data
    #     file_type = video_object.file_type
    #     video_duration = video_object.duration
    #     # We can also gather the frame_id, camera_type, timestamp and several other metadata

    # elif event.measurement.type == InspectionMeasurementType.IMT_AUDITIVE:
    #     metadata_type = AudioMetadata
    #     inspection_type = AnymalAudio

    #     audio_object = event.measurement.auditive
    #     file_bytes = audio_object.audio.data
    #     file_type = "mp3"
    #     # We can also gather the sampling rate, depth and number of channels from the audio metadata

    else:
        raise RobotRetrieveInspectionException(
            f"Unsupported inspection blob type {event.measurement.type} received"
        )

    return file_bytes, metadata_type, file_type, inspection_type, video_duration


def _fetch_blob_via_data_navigator(
    task_run_uid: str, request_handler: RequestHandler
) -> tuple[bytes, str]:
    inspection_response: Response = request_handler.get(
        url=f"{settings.SERVER_URL}/data-navigator-api/inspections?taskRunId={task_run_uid}"
    )
    inspection_response_json = inspection_response.json()
    total_items: int = inspection_response_json.get("totalItems", 0)
    items = inspection_response_json.get("items") or []

    if total_items < 1 or not items:
        raise RobotRetrieveInspectionException(
            f"Data-navigator returned no inspection items for "
            f"taskRunId={task_run_uid}"
        )
    if total_items > 1:
        logger.warning("Data-navigator returned %d items; using the first", total_items)

    try:
        file_name = items[0]["inspection"]["filename"]
    except (KeyError, TypeError) as exc:
        raise RobotRetrieveInspectionException(
            f"Data-navigator response missing inspection filename for "
            f"taskRunId={task_run_uid}"
        ) from exc
    max_retries: int = 30
    attempt_number: int = 0
    file_response: Response | None = None
    while attempt_number < max_retries:
        try:
            file_response = request_handler.get(
                url=f"{settings.SERVER_URL}/data-navigator-api/inspections/raw-data/{file_name}"
            )
        except RequestException:
            attempt_number += 1
            logger.warning(
                f"Failed to retrieve file on attempt {attempt_number} of {max_retries}"
            )
            time.sleep(1)
            continue

        break

    if file_response is None:
        error_description: str = f"Could not collect file with name {file_name}."
        logger.error(error_description)
        raise RobotRetrieveInspectionException(error_description)

    return file_response.content, file_response.headers["content-type"].split("/")[-1]


def _process_acoustic_inspection(
    event: InspectionEventDto,
    request_handler: RequestHandler,
    robot_pose: Pose,
    target_position: Position,
    task: TASKS,
) -> AcousticMeasurement:
    video_data: VideoMeasurementDto = VideoMeasurementDto.model_validate(
        event.measurement.data
    )

    leak_data: LeakDetectionInterpretationDto | None = None
    for interpretation in event.interpretations:
        if (
            interpretation.type == InspectionInterpretationType.IIT_LEAK_DETECTION
            and interpretation.data is not None
        ):
            leak_data = LeakDetectionInterpretationDto.model_validate(
                interpretation.data
            )
            break

    if leak_data is None:
        raise RobotRetrieveInspectionException(
            f"Acoustic inspection event for asset {event.asset_id} is missing IIT_LEAK_DETECTION data"
        )

    file_bytes, file_type = _fetch_blob_via_data_navigator(
        task_run_uid=event.task_run_uid, request_handler=request_handler
    )

    metadata = AcousticMeasurementMetadata(
        start_time=datetime.now(UTC),
        robot_pose=robot_pose,
        target_position=target_position,
        file_type=file_type,
        duration=video_data.duration,
        snr_value=leak_data.snr_value,
        leak_rate=leak_data.leak_rate,
        leak_rate_unit=leak_data.leak_rate_unit,
        sound_pressure_level_at_sensor_db=leak_data.sound_pressure_level_at_sensor_in_db,
        sound_pressure_level_at_source_db=leak_data.sound_pressure_level_at_source,
        distance_to_source=leak_data.distance_to_source,
        result=leak_data.result.value,
        frequency_from=leak_data.thumbnail_acoustic_image.frequency_range.min,
        frequency_to=leak_data.thumbnail_acoustic_image.frequency_range.max,
    )
    metadata.tag_id = task.tag_id
    metadata.inspection_description = task.inspection_description
    metadata.analysis_types = task.analysis_types

    return AcousticMeasurement(metadata=metadata, id=task.id, data=file_bytes)


def _extract_target_position(task: TASKS, robot_pose: Pose) -> Position:
    try:
        target_position: Position = task.target
    except AttributeError:
        logger.debug("No inspection target specified, using robot position instead")
        target_position = robot_pose.position
    return target_position


def _extract_robot_pose(event, transform: Transform) -> Pose:
    anymal_pose = event.measurement.sensor_pose.value
    pos = Position(
        x=anymal_pose.position.x,
        y=anymal_pose.position.y,
        z=anymal_pose.position.z,
        frame=Frame("robot"),
    )
    orientation = Orientation(
        x=anymal_pose.orientation.qx,
        y=anymal_pose.orientation.qy,
        z=anymal_pose.orientation.qz,
        w=anymal_pose.orientation.qw,
        frame=Frame("robot"),
    )

    robot_pose = Pose(position=pos, orientation=orientation, frame=Frame("robot"))
    robot_pose = transform.transform_pose(
        robot_pose, from_=Frame("robot"), to_=Frame("asset")
    )
    return robot_pose


def _is_acoustic_inspection(event) -> bool:
    if event.measurement.type != InspectionMeasurementType.IMT_VIDEO:
        return False
    return any(
        interpretation.type == InspectionInterpretationType.IIT_LEAK_DETECTION
        for interpretation in event.interpretations
    )


def _is_blob_inspection(event) -> bool:
    return (
        event.measurement.type == InspectionMeasurementType.IMT_VISUAL
        or event.measurement.type == InspectionMeasurementType.IMT_VIDEO
        or event.measurement.type == InspectionMeasurementType.IMT_AUDITIVE
        or event.measurement.type == InspectionMeasurementType.IMT_THERMAL
    )


def _is_value_inspection(event) -> bool:
    return event.measurement.type == InspectionMeasurementType.IMT_CONCENTRATION


def _create_blob_inspection(
    metadata_type: type[InspectionMetadata],
    inspection_type: type[Inspection],
    robot_pose: Pose,
    target_position: Position,
    file_type: str,
    task: TASKS,
    file_bytes: bytes,
    video_duration: int | None = None,
) -> Inspection:
    inspection_metadata: InspectionMetadata = metadata_type(
        start_time=datetime.now(UTC),
        robot_pose=robot_pose,
        target_position=target_position,
        file_type=file_type,
    )

    inspection_metadata.tag_id = task.tag_id
    inspection_metadata.inspection_description = task.inspection_description
    inspection_metadata.analysis_types = task.analysis_types

    if video_duration is not None and isinstance(
        inspection_metadata, (VideoMetadata, ThermalVideoMetadata, AudioMetadata)
    ):
        inspection_metadata.duration = video_duration

    return inspection_type(metadata=inspection_metadata, id=task.id, data=file_bytes)


def _create_value_inspection(
    task: TASKS,
    value: float,
    unit: str,
    metadata_type: type[InspectionMetadata],
    inspection_type: type[InspectionValue],
    robot_pose: Pose,
    target_position: Position,
):
    inspection_metadata: InspectionMetadata = metadata_type(
        start_time=datetime.now(UTC),
        robot_pose=robot_pose,
        target_position=target_position,
        file_type="",
    )

    inspection_metadata.tag_id = task.tag_id
    inspection_metadata.inspection_description = task.inspection_description
    inspection_metadata.analysis_types = task.analysis_types

    return inspection_type(
        id=task.id, unit=unit, value=value, metadata=inspection_metadata
    )
