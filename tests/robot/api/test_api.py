from pathlib import Path

import pytest
from alitra import Frame, Orientation, Pose, Position

from isar_anymal.robot.api.anymal_api.enums import (
    ANYmalMissionStatus,
    ANYmalTaskStatus,
    InspectionMeasurementType,
    Outcome,
    ResultInterpretation,
)
from isar_anymal.robot.api.anymal_api.models import (
    InspectionEventDto,
    TaskSummaryDto,
    TaskProgressDto,
)
from isar_anymal.robot.api.api import API
from isar_anymal.robot.api.mission_status_handler import MissionStatusHandler
from isar_anymal.robot.api.anymal_api.server_sent_event_handlers.inspection_handler import (
    _create_blob_inspection,
)
from pytest_mock import MockerFixture
from robot_interface.models.inspection.inspection import Image, ImageMetadata
from robot_interface.models.mission.status import MissionStatus, RobotStatus, TaskStatus
from robot_interface.models.mission.task import TakeImage
from robot_interface.models.robots.battery_state import BatteryState

from tests.robot.utilities import mock_subscribe_callback_functions


def test_create_inspection() -> None:
    robot_pose = Pose(
        position=Position(0, 0, 0, Frame("asset")),
        orientation=Orientation(x=0, y=0, z=0, w=1, frame=Frame("asset")),
        frame=Frame("asset"),
    )

    _create_blob_inspection(
        metadata_type=ImageMetadata,
        inspection_type=Image,
        robot_pose=robot_pose,
        target_position=robot_pose.position,
        file_type="jpg",
        task=TakeImage(
            target=Position(x=1, y=1, z=1, frame=Frame("asset")), robot_pose=robot_pose
        ),
        file_bytes=b"Some file bytes",
        video_duration=None,
    )


@pytest.mark.requires_private_test_data
def test_concentration_monitoring_inspection() -> None:
    test_data_dir: Path = Path(__file__).parent.parent / "test_data"
    concentration_monitoring_path: str = str(
        test_data_dir / "concentration_monitoring_example.json"
    )
    with open(concentration_monitoring_path, "r") as f:
        concentration_monitoring: str = f.read()

    inspection_event: InspectionEventDto = InspectionEventDto.model_validate_json(
        concentration_monitoring
    )
    assert (
        inspection_event.measurement.type
        == InspectionMeasurementType.IMT_CONCENTRATION_MONITORING
    )


@pytest.mark.requires_private_test_data
def test_visual_inspection() -> None:
    test_data_dir: Path = Path(__file__).parent.parent / "test_data"
    visual_inspection_path: str = str(test_data_dir / "inspection_visual_example.json")
    with open(visual_inspection_path, "r") as f:
        visual_inspection: str = f.read()

    inspection_event: InspectionEventDto = InspectionEventDto.model_validate_json(
        visual_inspection
    )
    assert inspection_event.measurement.type == InspectionMeasurementType.IMT_VISUAL


def test_robot_status_home_when_battery_is_charging_or_full(mocker) -> None:
    mock_subscribe_callback_functions(mocker)

    mocker.patch.object(
        API,
        "robot_is_online",
        return_value=True,
    )

    anymal: API = API()
    anymal.battery_handler.battery.state = BatteryState.Charging
    anymal.battery_handler.battery.level = 50.0

    robot_status: RobotStatus = anymal.get_robot_status()
    assert robot_status == RobotStatus.Home

    anymal.battery_handler.battery.state = BatteryState.Normal
    anymal.battery_handler.battery.level = 100.0
    robot_status = anymal.get_robot_status()
    assert robot_status == RobotStatus.Home


def test_robot_status_not_home_when_battery_is_not_charging_nor_full(mocker) -> None:
    mock_subscribe_callback_functions(mocker)

    anymal: API = API()
    anymal.battery_handler.battery.state = BatteryState.Normal
    anymal.battery_handler.battery.level = 50.0

    mocker.patch.object(
        API,
        "robot_is_online",
        return_value=True,
    )

    robot_status: RobotStatus = anymal.get_robot_status()
    assert robot_status != RobotStatus.Home


@pytest.mark.parametrize(
    "anymal_mission_status, anymal_task_summaries, expected_mission_status",
    [
        (
            ANYmalMissionStatus.MS_RUNNING,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_ONGOING,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                )
            ],
            MissionStatus.InProgress,
        ),
        (
            ANYmalMissionStatus.MS_PAUSED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_PREEMPTED,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                )
            ],
            MissionStatus.Paused,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                )
            ],
            MissionStatus.Successful,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            MissionStatus.PartiallySuccessful,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            MissionStatus.Failed,
        ),
        (
            ANYmalMissionStatus.MS_COMPLETED,
            [
                TaskSummaryDto(
                    taskId="undock",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            MissionStatus.Failed,
        ),
    ],
)
def test_get_mission_status(
    anymal_mission_status,
    anymal_task_summaries,
    expected_mission_status,
    mocker: MockerFixture,
) -> None:
    mock_subscribe_callback_functions(mocker)

    mocker.patch.object(
        MissionStatusHandler,
        "_get_anymal_mission_status",
        return_value=anymal_mission_status,
    )
    mocker.patch.object(
        MissionStatusHandler,
        "_get_anymal_task_summaries",
        return_value=anymal_task_summaries,
    )
    anymal: API = API()

    assert anymal.get_mission_status() == expected_mission_status


@pytest.mark.parametrize(
    "task_id, anymal_task_summaries, expected_task_status",
    [
        (
            "1",
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_ONGOING,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.Successful,
        ),
        (
            "2",
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_SUCCESS,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_ONGOING,
                    progress=TaskProgressDto(progress=0.5, target=1.0, unit="m"),
                    outcome=Outcome.OC_NA,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.InProgress,
        ),
        (
            "2",
            [
                TaskSummaryDto(
                    taskId="1",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
                TaskSummaryDto(
                    taskId="2",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.Failed,
        ),
        (
            "2",
            [
                TaskSummaryDto(
                    taskId="undock",
                    status=ANYmalTaskStatus.TS_COMPLETED,
                    progress=TaskProgressDto(progress=1.0, target=1.0, unit="m"),
                    outcome=Outcome.OC_FAILURE,
                    resultInterpretation=ResultInterpretation.RI_NA,
                ),
            ],
            TaskStatus.Failed,
        ),
    ],
)
def test_get_task_status(
    task_id,
    anymal_task_summaries,
    expected_task_status,
    mocker: MockerFixture,
) -> None:
    mock_subscribe_callback_functions(mocker)
    mocker.patch.object(
        MissionStatusHandler,
        "_get_anymal_task_summaries",
        return_value=anymal_task_summaries,
    )
    anymal: API = API()

    assert anymal.get_task_status(task_id) == expected_task_status
