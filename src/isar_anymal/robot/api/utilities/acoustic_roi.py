import logging

from robot_interface.models.mission.task import Roi

logger = logging.getLogger(__name__)


# Default ROI for acoustic-imaging inspections. The pixel coordinates and
# extents come from an example acoustic video returned by the data-navigator
# API; the robot expects request ROIs to fall within the same rectangle
# (x in [968, 2905], y in [1513, 4539]). DEFAULT_ACOUSTIC_ROI doubles as the
# validation envelope in resolve_acoustic_roi: out-of-bounds ROIs are replaced
# with this default rather than rejected.
DEFAULT_ACOUSTIC_ROI: dict[str, int] = {
    "x": 968,
    "y": 1513,
    "width": 1937,
    "height": 3026,
}


def resolve_acoustic_roi(task_roi: Roi | None) -> dict[str, int]:
    if task_roi is None:
        return dict(DEFAULT_ACOUSTIC_ROI)

    x_min: int = DEFAULT_ACOUSTIC_ROI["x"]
    y_min: int = DEFAULT_ACOUSTIC_ROI["y"]
    x_max: int = x_min + DEFAULT_ACOUSTIC_ROI["width"]
    y_max: int = y_min + DEFAULT_ACOUSTIC_ROI["height"]

    if (
        task_roi.x < x_min
        or task_roi.y < y_min
        or task_roi.x + task_roi.width > x_max
        or task_roi.y + task_roi.height > y_max
    ):
        logger.warning(
            "Acoustic ROI %s falls outside the supported envelope "
            "(x in [%d, %d], y in [%d, %d]); using default ROI %s",
            task_roi.model_dump(),
            x_min,
            x_max,
            y_min,
            y_max,
            DEFAULT_ACOUSTIC_ROI,
        )
        return dict(DEFAULT_ACOUSTIC_ROI)

    return {
        "x": task_roi.x,
        "y": task_roi.y,
        "width": task_roi.width,
        "height": task_roi.height,
    }
