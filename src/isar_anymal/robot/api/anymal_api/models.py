from typing import List, Union

from pydantic import BaseModel, Field

from isar_anymal.robot.api.anymal_api.enums import (
    ANYmalServiceCallStatus,
    BatteryStatus,
    ControlMissionStatus,
    ServiceCallStatus,
    UserInteractionMode,
    ClientType,
    ProtectiveStopOrigin,
    MissionType,
    ANYmalMissionStatus,
    ANYmalTaskStatus,
    Outcome,
    ResultInterpretation,
    InspectionMeasurementType,
    InspectionInterpretationType,
    MeasuredTemperatureType,
    SubstanceConcentrationLevel,
    InterpretationConfidenceLevel,
)


class LeaseControlResponseDto(BaseModel):
    lease_id: str = Field(alias="leaseId")
    status: ServiceCallStatus = Field(alias="status")
    message: str = Field(alias="message")


class ReleaseControlResponseDto(BaseModel):
    status: ServiceCallStatus = Field(alias="status")
    message: str = Field(alias="message")


class Header(BaseModel):
    timestamp: str = Field(alias="timestamp")
    status: ANYmalServiceCallStatus = Field(alias="status")
    message: str = Field(alias="message")


class GetUserInteractionModeResponseDto(BaseModel):
    header: Header = Field(alias="header")
    user_interaction_mode: UserInteractionMode = Field(alias="userInteractionMode")


class SetUserInteractionModeResponseDto(BaseModel):
    header: Header = Field(alias="header")


class ProtectiveStopResponseDto(BaseModel):
    status: ServiceCallStatus = Field(alias="status")
    message: str = Field(alias="message")


class ControlMissionResponseDto(BaseModel):
    status: ANYmalServiceCallStatus = Field(alias="status")
    control_mission_status: ControlMissionStatus = Field(alias="controlMissionStatus")
    timestamp: str = Field(alias="timestamp")
    run_uid: str = Field(alias="runUid")
    message: str = Field(alias="message")


class BatteryStateDto(BaseModel):
    state_of_charge: float = Field(alias="stateOfCharge")
    voltage: float = Field(alias="voltage")
    status: BatteryStatus = Field(alias="status")


class RobotMetaDataDto(BaseModel):
    robot_name: str = Field(alias="robotName")


class MainBodyStateDto(BaseModel):
    relative_humidity: float = Field(alias="relativeHumidity")
    differential_pressure: float = Field(alias="differentialPressure")
    temperature: float = Field(alias="temperature")


class PositionDto(BaseModel):
    x: float | None = Field(alias="x", default=None)
    y: float | None = Field(alias="y", default=None)
    z: float | None = Field(alias="z", default=None)


class OrientationDto(BaseModel):
    qx: float | None = Field(alias="qx", default=None)
    qy: float | None = Field(alias="qy", default=None)
    qz: float | None = Field(alias="qz", default=None)
    qw: float | None = Field(alias="qw", default=None)


class PoseValueDto(BaseModel):
    position: PositionDto | None = Field(alias="position", default=None)
    orientation: OrientationDto | None = Field(alias="orientation", default=None)


class PoseDto(BaseModel):
    frame_id: str | None = Field(alias="frameId", default=None)
    value: PoseValueDto | None = Field(alias="value", default=None)


class PoseAtTimeDto(BaseModel):
    timestamp: str | None = Field(alias="timestamp", default=None)
    pose: PoseDto | None = Field(alias="pose", default=None)


class ProtectiveStopStatusDto(BaseModel):
    is_engaged: bool = Field(alias="isEngaged")
    origin: ProtectiveStopOrigin = Field(alias="origin")


class ControlAuthorityStatusDto(BaseModel):
    client_name: str = Field(alias="clientName")
    client_type: ClientType = Field(alias="clientType")


class MissionMetadataDto(BaseModel):
    robot_name: str = Field(alias="robotName")
    mission_id: str = Field(alias="missionId")
    mission_run_id: str = Field(alias="missionRunId")
    mission_type: MissionType = Field(alias="missionType")


class TaskProgressDto(BaseModel):
    progress: float = Field(alias="progress")
    target: float = Field(alias="target")
    unit: str = Field(alias="unit")


class TaskSummaryDto(BaseModel):
    task_id: str = Field(alias="taskId")
    status: ANYmalTaskStatus = Field(alias="status")
    progress: TaskProgressDto | None = Field(alias="progress", default=None)
    outcome: Outcome = Field(alias="outcome")
    result_interpretation: ResultInterpretation = Field(alias="resultInterpretation")


class MissionSummaryDto(BaseModel):
    status: ANYmalMissionStatus = Field(alias="status")
    task_summaries: List[TaskSummaryDto] = Field(alias="taskSummaries")
    outcome: Outcome = Field(alias="outcome")


class ImageDto(BaseModel):
    width: float = Field(alias="width")
    height: float = Field(alias="height")
    encoding: str = Field(alias="encoding")
    step: float = Field(alias="step")
    data: str = Field(alias="data")


class VisualMeasurementDto(BaseModel):
    image: ImageDto = Field(alias="image")


class ThermalImageDto(BaseModel):
    image: ImageDto = Field(alias="image")
    gain: float = Field(alias="gain")
    offset: float = Field(alias="offset")


class ThermalMeasurementDto(BaseModel):
    thermal_image: str = Field(alias="thermalImage")


class AudioDataDto(BaseModel):
    sampling_rate: float = Field(alias="samplingRate")
    channels: int = Field(alias="channels")
    depth: float = Field(alias="depth")
    data: str = Field(alias="data")
    duration: float = Field(alias="duration")


class AuditiveMeasurementDto(BaseModel):
    audio: AudioDataDto = Field(alias="audio")


class AudioVideoParametersDto(BaseModel):
    bit_rate: float = Field(alias="bitRate")
    encoding: str = Field(alias="encoding")
    format: str = Field(alias="format")


class VideoMeasurementDto(BaseModel):
    timestamp: str = Field(alias="timestamp")
    frame_id: str = Field(alias="frameId")
    camera_type: str = Field(alias="cameraType")
    digest: str = Field(alias="digest")
    file_size: str = Field(alias="fileSize")
    frame_rate: float = Field(alias="frameRate")
    width: float = Field(alias="width")
    height: float = Field(alias="height")
    file_type: str = Field(alias="fileType")
    video_params: AudioVideoParametersDto = Field(alias="videoParameters")
    audio_params: AudioVideoParametersDto = Field(alias="audioParameters")
    video_data: str = Field(alias="videoData")


class FloatRangeDto(BaseModel):
    min: float = Field(alias="min")
    max: float = Field(alias="max")
    exclusive_min: bool = Field(alias="exclusiveMin")
    exclusive_max: bool = Field(alias="exclusiveMax")


class ConcentrationThresholdsDto(BaseModel):
    warning: float = Field(alias="warning")
    alarm: float = Field(alias="alarm")


class ConcentrationSensorPropertiesDto(BaseModel):
    unit: str = Field(alias="unit")
    substance: str = Field(alias="substance")
    measurement_range: FloatRangeDto = Field(alias="measurementRange")
    low_thresholds: ConcentrationThresholdsDto | None = Field(
        alias="lowThresholds", default=None
    )
    high_thresholds: ConcentrationThresholdsDto = Field(alias="highThresholds")


class ConcentrationMeasurementDto(BaseModel):
    value: float | None = Field(alias="value", default=None)
    sensor_properties: ConcentrationSensorPropertiesDto = Field(
        alias="sensorProperties"
    )


class AcousticImageMeasurementDto(BaseModel):
    image: ImageDto = Field(alias="image")


class InspectionMeasurementDto(BaseModel):
    type: InspectionMeasurementType = Field(alias="type")
    sensor_pose: PoseDto = Field(alias="sensorPose")
    data: Union[
        ThermalMeasurementDto,
        AuditiveMeasurementDto,
        VisualMeasurementDto,
        VideoMeasurementDto,
        ConcentrationMeasurementDto,
        AcousticImageMeasurementDto,
    ]


class ThermalHotspotInterpretationDto(BaseModel):
    confidence: float = Field(alias="confidence")
    min_temperature: float = Field(alias="minTemperature")
    max_temperature: float = Field(alias="maxTemperature")
    spot_temperature: float = Field(alias="spotTemperature")
    measured_temperature_type: MeasuredTemperatureType = Field(
        alias="measuredTemperatureType"
    )
    colorized_image: ImageDto = Field(alias="colorizedImage")
    result: ResultInterpretation = Field(alias="result")
    normal_operating_range: FloatRangeDto = Field(alias="normalOperatingRange")


class AuditiveSampleCaptureInterpretationDto(BaseModel):
    pass


class AuditiveFrequencyAnalysisConfigurationDto(BaseModel):
    desired_frequencies: List[float] = Field(alias="desiredFrequencies")
    filter_frequencies: List[float] = Field(alias="filterFrequencies")
    frequency_expected: bool = Field(alias="frequencyExpected")
    snr_value_threshold: float = Field(alias="snrValueThreshold")
    use_signal_harmonics: bool = Field(alias="useSignalHarmonics")
    use_filter_harmonics: bool = Field(alias="useFilterHarmonics")
    is_ultrasonic: bool = Field(alias="isUltrasonic")


class AuditiveFrequencyAnalysisInterpretationDto(BaseModel):
    confidence: float = Field(alias="confidence")
    power_spectrum: ImageDto = Field(alias="powerSpectrum")
    signal_to_noise_ratio: float = Field(alias="signalToNoiseRatio")
    configuration: AuditiveFrequencyAnalysisConfigurationDto = Field(
        alias="configuration"
    )
    frequency_detected: bool = Field(alias="frequencyDetected")
    fft_frequency: List[float] = Field(alias="fftFrequency")
    fft_power: List[float] = Field(alias="fftPower")
    result: ResultInterpretation = Field(alias="result")


class VisualFrameCaptureInterpretationDto(BaseModel):
    pass


class VisualReadoutInterpretationDto(BaseModel):
    confidence: float = Field(alias="confidence")
    estimate: float = Field(alias="estimate")
    estimate_units: str = Field(alias="estimateUnits")
    detection_image: ImageDto = Field(alias="detectionImage")
    asset_type: str = Field(alias="assetType")
    result: ResultInterpretation = Field(alias="result")


class VisualObjectDetectionInterpretationDto(BaseModel):
    confidence: float = Field(alias="confidence")
    detection_image: ImageDto = Field(alias="detectionImage")
    asset_type: str = Field(alias="assetType")
    result: ResultInterpretation = Field(alias="result")
    confidence_threshold: float = Field(alias="confidenceThreshold")


class VideoInterpretationDto(BaseModel):
    pass


class ConcentrationInterpretationDto(BaseModel):
    confidence: float = Field(alias="confidence")
    concentration_level: SubstanceConcentrationLevel = Field(alias="concentrationLevel")
    confidence_level: InterpretationConfidenceLevel = Field(alias="confidenceLevel")


class AcousticImageFrameCaptureInterpretationDto(BaseModel):
    pass


class LeakDetectionConfigurationDto(BaseModel):
    gas_cost: float = Field(alias="gasCost")
    electricity_cost: float = Field(alias="electricityCost")
    power_ratio: float = Field(alias="powerRatio")
    operating_hours_per_year: float = Field(alias="operatingHoursPerYear")
    snr_value_threshold: float = Field(alias="snrValueThreshold")


class AcousticImageDto(BaseModel):
    image: ImageDto = Field(alias="image")
    frequency_range: FloatRangeDto = Field(alias="frequencyRange")


class MechanicalInspectionConfigurationDto(BaseModel):
    base_frequency: float = Field(alias="baseFrequency")
    snr_value_threshold: float = Field(alias="snrValueThreshold")
    frequency_expected: bool = Field(alias="frequencyExpected")


class LeakDetectionInterpretationDto(BaseModel):
    result: ResultInterpretation = Field(alias="result")
    configuration: LeakDetectionConfigurationDto = Field(alias="configuration")
    distance_to_source: float = Field(alias="distanceToSource")
    sound_pressure_level_at_source: float = Field(alias="soundPressureLevelAtSource")
    snr_value: float = Field(alias="snrValue")
    cost: float = Field(alias="cost")
    cost_unit: str = Field(alias="costUnit")
    electricity_usage: float = Field(alias="electricityUsage")
    electricity_usage_unit: str = Field(alias="electricityUsageUnit")
    leak_rate: float = Field(alias="leakRate")
    leak_rate_unit: str = Field(alias="leakRateUnit")
    thumbnail_acoustic_image: AcousticImageDto = Field(alias="thumbnailAcousticImage")


class MechanicalInspectionInterpretationDto(BaseModel):
    result: ResultInterpretation = Field(alias="result")
    configuration: MechanicalInspectionConfigurationDto = Field(alias="configuration")
    distance_to_source: float = Field(alias="distanceToSource")
    sound_pressure_level_at_source: float = Field(alias="soundPressureLevelAtSource")
    snr_value: float = Field(alias="snrValue")
    thumbnail_acoustic_image: AcousticImageDto = Field(alias="thumbnailAcousticImage")


class PartialDischargeDetectionConfigurationDto(BaseModel):
    operating_conditions: str = Field(alias="operatingConditions")
    snr_value_threshold: float = Field(alias="snrValueThreshold")


class PartialDischargeDetectionInterpretationDto(BaseModel):
    result: ResultInterpretation = Field(alias="result")
    configuration: PartialDischargeDetectionConfigurationDto = Field(
        alias="configuration"
    )
    distance_to_source: float = Field(alias="distanceToSource")
    sound_pressure_level_at_source: float = Field(alias="soundPressureLevelAtSource")
    snr_value: float = Field(alias="snrValue")
    external_probability: float = Field(alias="externalProbability")
    internal_probability: float = Field(alias="internalProbability")
    surface_tracking_probability: float = Field(alias="surfaceTrackingProbability")
    thumbnail_acoustic_image: AcousticImageDto = Field(alias="thumbnailAcousticImage")


class InspectionInterpretationDto(BaseModel):
    type: InspectionInterpretationType = Field(alias="type")
    data: (
        Union[
            ThermalHotspotInterpretationDto,
            AuditiveSampleCaptureInterpretationDto,
            AuditiveFrequencyAnalysisInterpretationDto,
            VisualFrameCaptureInterpretationDto,
            VisualReadoutInterpretationDto,
            VisualObjectDetectionInterpretationDto,
            VideoInterpretationDto,
            ConcentrationInterpretationDto,
            AcousticImageFrameCaptureInterpretationDto,
            LeakDetectionInterpretationDto,
            MechanicalInspectionInterpretationDto,
            PartialDischargeDetectionInterpretationDto,
        ]
        | None
    ) = Field(alias="data", default=None)


class EventBaseModel(BaseModel):
    pass


class PhysicalConditionEventDto(EventBaseModel):
    timestamp: str = Field(alias="timestamp")
    metadata: RobotMetaDataDto | None = Field(alias="metadata", default=None)
    battery_state: BatteryStateDto | None = Field(alias="batteryState", default=None)
    main_body_state: MainBodyStateDto | None = Field(
        alias="mainBodyState", default=None
    )


class StateEventDto(EventBaseModel):
    timestamp: str = Field(alias="timestamp")
    pose: PoseAtTimeDto | None = Field(alias="pose", default=None)


class ControlStatusEventDto(EventBaseModel):
    timestamp: str = Field(alias="timestamp")
    metadata: RobotMetaDataDto | None = Field(alias="metadata", default=None)
    control_authority_status: ControlAuthorityStatusDto | None = Field(
        alias="controlAuthorityStatus", default=None
    )
    is_power_cut: bool = Field(alias="isPowerCut")
    protective_stop_status: ProtectiveStopStatusDto | None = Field(
        alias="protectiveStopStatus", default=None
    )
    user_interaction_mode: UserInteractionMode | None = Field(
        alias="userInteractionMode", default=None
    )


class MissionEventDto(EventBaseModel):
    timestamp: str = Field(alias="timestamp")
    metadata: MissionMetadataDto | None = Field(alias="metadata", default=None)
    mission_summary: MissionSummaryDto | None = Field(
        alias="missionSummary", default=None
    )


class InspectionEventDto(EventBaseModel):
    timestamp: str = Field(alias="timestamp")
    asset_id: str = Field(alias="assetId")
    metadata: MissionMetadataDto | None = Field(alias="metadata", default=None)
    measurement: InspectionMeasurementDto | None = Field(
        alias="measurement", default=None
    )
    interpretations: List[InspectionInterpretationDto] = Field(alias="interpretations")
    task_run_uid: str = Field(alias="taskRunUid")
    environment_id: str = Field(alias="environmentId")
