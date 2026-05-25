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
    lease_id: str | None = Field(alias="leaseId", default=None)
    status: ServiceCallStatus = Field(alias="status")
    message: str | None = Field(alias="message", default=None)


class ReleaseControlResponseDto(BaseModel):
    status: ServiceCallStatus = Field(alias="status")
    message: str | None = Field(alias="message", default=None)


class Header(BaseModel):
    timestamp: str = Field(alias="timestamp")
    status: ANYmalServiceCallStatus = Field(alias="status")
    message: str | None = Field(alias="message", default=None)


class GetUserInteractionModeResponseDto(BaseModel):
    header: Header | None = Field(alias="header", default=None)
    user_interaction_mode: UserInteractionMode = Field(alias="userInteractionMode")


class SetUserInteractionModeResponseDto(BaseModel):
    header: Header | None = Field(alias="header", default=None)


class ProtectiveStopResponseDto(BaseModel):
    status: ServiceCallStatus = Field(alias="status")
    message: str | None = Field(alias="message", default=None)


class ControlMissionResponseDto(BaseModel):
    status: ANYmalServiceCallStatus = Field(alias="status")
    control_mission_status: ControlMissionStatus = Field(alias="controlMissionStatus")
    timestamp: str = Field(alias="timestamp")
    run_uid: str = Field(alias="runUid")
    message: str | None = Field(alias="message", default=None)


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
    data: str | None = Field(alias="data", default=None)


class VisualMeasurementDto(BaseModel):
    image: ImageDto | None = Field(alias="image", default=None)


class ThermalImageDto(BaseModel):
    image: ImageDto = Field(alias="image")
    gain: float = Field(alias="gain")
    offset: float = Field(alias="offset")


class ThermalMeasurementDto(BaseModel):
    thermal_image: ThermalImageDto | None = Field(alias="thermalImage", default=None)
    rgb_image: ImageDto | None = Field(alias="rgbImage", default=None)
    rgb_pose: PoseDto | None = Field(alias="rgbPose", default=None)


class AudioDataDto(BaseModel):
    sampling_rate: float = Field(alias="samplingRate")
    channels: int = Field(alias="channels")
    depth: float = Field(alias="depth")
    data: str | None = Field(alias="data", default=None)
    duration: float = Field(alias="duration")


class AuditiveMeasurementDto(BaseModel):
    fans_shutoff: bool = Field(alias="fansShutoff")
    audio: AudioDataDto | None = Field(alias="audio", default=None)


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
    duration: float = Field(alias="duration")
    frame_rate: float = Field(alias="frameRate")
    width: float = Field(alias="width")
    height: float = Field(alias="height")
    file_type: str = Field(alias="fileType")
    fans_shutoff: bool = Field(alias="fansShutoff")
    video_params: AudioVideoParametersDto | None = Field(
        alias="videoParams", default=None
    )
    audio_params: AudioVideoParametersDto | None = Field(
        alias="audioParams", default=None
    )
    video_data: str | None = Field(alias="videoData", default=None)


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
    measurement_range: FloatRangeDto | None = Field(
        alias="measurementRange", default=None
    )
    low_thresholds: ConcentrationThresholdsDto = Field(alias="lowThresholds")
    high_thresholds: ConcentrationThresholdsDto = Field(alias="highThresholds")


class ConcentrationMeasurementDto(BaseModel):
    value: float | None = Field(alias="value", default=None)
    sensor_properties: ConcentrationSensorPropertiesDto = Field(
        alias="sensorProperties"
    )


class Size2dDto(BaseModel):
    width: float = Field(alias="width")
    height: float = Field(alias="height")


class RectangleDto(BaseModel):
    x: float = Field(alias="x")
    y: float = Field(alias="y")
    width: float = Field(alias="width")
    height: float = Field(alias="height")


class AcousticImagingRoiDto(BaseModel):
    rectangle: RectangleDto = Field(alias="rectangle")
    image_size: Size2dDto = Field(alias="imageSize")


class AcousticImageDto(BaseModel):
    image: ImageDto = Field(alias="image")
    frequency_range: FloatRangeDto = Field(alias="frequencyRange")
    roi: AcousticImagingRoiDto = Field(alias="roi")


class AcousticImageMeasurementDto(BaseModel):
    fans_shutoff: bool = Field(alias="fansShutoff")
    acoustic_image: AcousticImageDto | None = Field(alias="acousticImage", default=None)


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
    colorized_image: ImageDto | None = Field(alias="colorizedImage", default=None)
    result: ResultInterpretation = Field(alias="result")
    normal_operating_range: FloatRangeDto | None = Field(
        alias="normalOperatingRange", default=None
    )
    median_temperature: float = Field(alias="medianTemperature")
    roi_diameter: float = Field(alias="roiDiameter")
    emissivity: float = Field(alias="emissivity")
    ambient_temperature: float = Field(alias="ambientTemperature")
    ambient_relative_humidity: float = Field(alias="ambientRelativeHumidity")
    distance_to_asset: float = Field(alias="distanceToAsset")
    atmospheric_transmission: float = Field(alias="atmosphericTransmission")


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
    bin_tolerance: float = Field(alias="binTolerance")
    harmonics_to_use: float = Field(alias="harmonicsToUse")
    analysis_window: float = Field(alias="analysisWindow")


class AuditiveFrequencyAnalysisInterpretationDto(BaseModel):
    confidence: float = Field(alias="confidence")
    power_spectrum: ImageDto | None = Field(alias="powerSpectrum", default=None)
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
    detection_image: ImageDto | None = Field(alias="detectionImage", default=None)
    asset_type: str = Field(alias="assetType")
    result: ResultInterpretation = Field(alias="result")
    confidence_threshold: float = Field(alias="confidenceThreshold")
    normal_operating_range: FloatRangeDto | None = Field(
        alias="normalOperatingRange", default=None
    )
    measurement_range: FloatRangeDto | None = Field(
        alias="measurementRange", default=None
    )


class VisualObjectDetectionInterpretationDto(BaseModel):
    confidence: float = Field(alias="confidence")
    detection_image: ImageDto | None = Field(alias="detectionImage", default=None)
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


class MechanicalInspectionConfigurationDto(BaseModel):
    snr_value_threshold: float = Field(alias="snrValueThreshold")


class LeakDetectionInterpretationDto(BaseModel):
    # DEPRECATED in spec but still required on the wire
    sound_pressure_level_at_sensor_in_db: float = Field(
        alias="soundPressureLevelAtSensorInDb"
    )
    signal_to_noise_ratio_in_db: float = Field(alias="signalToNoiseRatioInDb")
    leakq_scale_at_source: float = Field(alias="leakqScaleAtSource")
    leakq_threshold: float = Field(alias="leakqThreshold")
    thumbnail_image: ImageDto | None = Field(alias="thumbnailImage", default=None)
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
    sound_pressure_level_at_sensor: float = Field(alias="soundPressureLevelAtSensor")
    sound_pressure_level_beamformed_min: float = Field(
        alias="soundPressureLevelBeamformedMin"
    )
    sound_pressure_level_beamformed_max: float = Field(
        alias="soundPressureLevelBeamformedMax"
    )


class PartialDischargeDetectionConfigurationDto(BaseModel):
    operating_conditions: str = Field(alias="operatingConditions")
    snr_value_threshold: float = Field(alias="snrValueThreshold")


class PartialDischargeDetectionInterpretationDto(BaseModel):
    # DEPRECATED in spec but still required on the wire
    sound_pressure_level_at_sensor_in_db: float = Field(
        alias="soundPressureLevelAtSensorInDb"
    )
    discharge_pulses_per_minute: float = Field(alias="dischargePulsesPerMinute")
    discharge_pulses_threshold: float = Field(alias="dischargePulsesThreshold")
    thumbnail_image: ImageDto | None = Field(alias="thumbnailImage", default=None)
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
