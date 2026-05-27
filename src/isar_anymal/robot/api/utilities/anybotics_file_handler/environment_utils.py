import yaml

thermal_inspection = yaml.load(
    """label: "[label]"
min_certainty: 0.6
name: "[name]"
normal_operating_range:
    max: 900.0
    min: -20.0
pose:
    header:
        frame_id: map
    pose:
        orientation:
            w: 0.737308988858222
            x: 0.674585715570665
            y: 0.0136916610744799
            z: -0.0334978464069242
        position:
            x: 0
            y: 0
            z: 0
roi_diameter: 5.0
temperature_type: Max
type: visual_inspection_thermal
unit: degreesC""",
    Loader=yaml.FullLoader,
)

nav_goal = yaml.load(
    """label: T1_1_nav
name: T1_1_nav
pose:
    header:
        frame_id: map
    pose:
        orientation:
            w: 0.999349136435361
            x: 0.0219349567325624
            y: 0.0069751769007747
            z: 0.0277761645937201
        position:
            x: 17.13
            y: 7.38
            z: -0.71
    tolerance:
        rotation: 0.104719758033752
        translation: 0.0500000007450581
type: navigation_goal""",
    Loader=yaml.FullLoader,
)

nav_zone = yaml.load(
    """label: T1_1_navZone
name: T1_1_navZone
type: navigation_zone""",
    Loader=yaml.FullLoader,
)

visual_inspection = yaml.load(
    """camera_mode: full_auto
camera_type: normal
label: T1_1_P1
name: T1_1_P1
pose:
    header:
        frame_id: map
    pose:
        orientation:
            w: 0.737308988858222
            x: 0.674585715570665
            y: 0.0136916610744799
            z: -0.0334978464069242
        position:
            x: 16.92
            y: 5.25
            z: 0.17
size:
    height: 10
    width: 10
type: visual_inspection_simple""",
    Loader=yaml.FullLoader,
)

relation = yaml.load(
    """child: T1_1_nav
parent: T1_1_navZone""",
    Loader=yaml.FullLoader,
)

acoustic_inspection = yaml.load(
    """autopoint_type: full
detection_type: "[detection_type]"
electricity_cost: 0.0
frame_id: map
frequency_from: "[frequency_from]"
frequency_to: "[frequency_to]"
gas_cost: 0.0
label: "[label]"
name: "[name]"
operating_conditions: DC
operating_hours_per_year: 0.0
pose:
    header:
        frame_id: map
    pose:
        orientation:
            w: 1.0
            x: 0.0
            y: 0.0
            z: 0.0
        position:
            x: 0
            y: 0
            z: 0
power_ratio: 0.0
snr_value_threshold: "[snr_value_threshold]"
type: acoustic_imaging""",
    Loader=yaml.FullLoader,
)


def set_coordinate(item, coordinate):
    item["pose"]["pose"]["position"]["x"] = coordinate[0]
    item["pose"]["pose"]["position"]["y"] = coordinate[1]
    item["pose"]["pose"]["position"]["z"] = coordinate[2]


def set_orientation(item, orientation):
    item["pose"]["pose"]["orientation"]["w"] = orientation["w"]
    item["pose"]["pose"]["orientation"]["x"] = orientation["x"]
    item["pose"]["pose"]["orientation"]["y"] = orientation["y"]
    item["pose"]["pose"]["orientation"]["z"] = orientation["z"]


def load_environment(filename: str):
    with open(filename) as file:
        environment = yaml.load(file, Loader=yaml.FullLoader)
        return environment


def get_item_from_name(environment, item_name):
    for item in environment["objects"]:
        if item["name"] == item_name:
            return item

    return None


def get_nav_zone_from_inspection(environment, inspection_name):
    for relation in environment["object_relations"]:
        if relation["parent"] == inspection_name:
            return relation["child"]


def get_nav_goal_from_zone(environment, zone_name):
    for relation in environment["object_relations"]:
        if relation["parent"] == zone_name:
            return relation["child"]


def get_nav_goal_from_inspection(environment, inspection_name):
    zone_name = get_nav_zone_from_inspection(environment, inspection_name)
    return get_nav_goal_from_zone(environment, zone_name)
