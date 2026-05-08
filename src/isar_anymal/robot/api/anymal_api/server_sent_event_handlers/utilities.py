from pathlib import Path

from alitra import MapAlignment, Transform, align_maps

from isar_anymal.config import settings


def import_transform_from_map_file():
    map_path = (
        Path(__file__)
        .parent.parent.parent.parent.parent.joinpath(
            f"./config/maps/{settings.MAP_NAME}.json"
        )
        .resolve()
    )
    map_alignment: MapAlignment = MapAlignment.from_config(map_path)
    transform: Transform = align_maps(
        map_from=map_alignment.map_from, map_to=map_alignment.map_to, rot_axes="z"
    )

    return transform
