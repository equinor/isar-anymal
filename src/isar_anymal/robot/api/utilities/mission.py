from robot_interface.models.mission.mission import Mission
from robot_interface.models.mission.task import TaskTypes


def is_return_to_home_mission(mission: Mission) -> bool:
    if len(mission.tasks) != 1:
        return False

    return mission.tasks[0].type is TaskTypes.ReturnToHome
