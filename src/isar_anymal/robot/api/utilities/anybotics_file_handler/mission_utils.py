import yaml

mission_template = yaml.load(
    """name: "[name]"
settings:
  - name: default_initial_state
    type: DefaultInitialState
    value: "[undock]"
  - name: outcomes
    type: Outcomes
    value:
      - failure
      - preemption
      - success
  - name: restart_on_execution
    type: bool
    value: false
  - name: states
    type: States
    value: "[list_of_states]"
type: state_machine::DynamicStateMachine""",
    Loader=yaml.FullLoader,
)

sleep_task = yaml.load(
    """name: "[task_name]"
settings:
  - name: duration
    type: double
    value: 5.0
transitions:
  - outcome: failure
    transition: failure
    transition_to_state: false
  - outcome: preemption
    transition: preemption
    transition_to_state: false
  - outcome: success
    transition: "[next_task_name]"
    transition_to_state: true
type: basic_behavior_plugins::Sleep""",
    Loader=yaml.FullLoader,
)

undock_task = yaml.load(
    """name: Undock
settings:
  []
transitions:
  - outcome: failure
    transition: failure
    transition_to_state: false
  - outcome: preemption
    transition: preemption
    transition_to_state: false
  - outcome: success
    transition: "[next_task_name]"
    transition_to_state: true
type: system_behavior_plugins::Walk""",
    Loader=yaml.FullLoader,
)

dock_task = yaml.load(
    """name: Dock
settings:
  []
transitions:
  - outcome: failure
    transition: failure
    transition_to_state: false
  - outcome: preemption
    transition: preemption
    transition_to_state: false
  - outcome: success
    transition: success
    transition_to_state: false
type: system_behavior_plugins::Dock""",
    Loader=yaml.FullLoader,
)

inspection_task = yaml.load(
    """name: "[task_name]"
settings:
  - name: inspectable_item
    type: InspectableItem
    value: "[item_name]"
transitions:
  - outcome: anomaly
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: failure
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: normal
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: preemption
    transition: preemption
    transition_to_state: false
type: "[plugin_name]::[plugin_action]" """,
    Loader=yaml.FullLoader,
)

simple_inspection_task = yaml.load(
    """name: "[task_name]"
settings:
  - name: inspectable_item
    type: InspectableItem
    value: "[item_name]"
transitions:
  - outcome: failure
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: success
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: preemption
    transition: preemption
    transition_to_state: false
type: "[plugin_name]::[plugin_action]" """,
    Loader=yaml.FullLoader,
)

navigation_task = yaml.load(
    """name: "[task_name]"
settings:
  - name: navigation_goal
    type: NavigationGoal
    value: "[item_name]"
  - name: route_option
    type: RouteOption
    value: Along Waypoints
transitions:
  - outcome: failure
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: preemption
    transition: preemption
    transition_to_state: false
  - outcome: success
    transition: "[next_task_name]"
    transition_to_state: true
type: navigation_behavior_plugins::ReactiveNavigation""",
    Loader=yaml.FullLoader,
)

co2_measurement_task = yaml.load(
    """name: "[task_name]"
settings:
  - name: navigation_goal
    type: NavigationGoal
    value: "[item_name]"
  - name: inspection_modality
    type: InspectionModality
    value: Gas Concentration Sensor 1
transitions:
  - outcome: anomaly
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: failure
    transition: "[next_task_name]"
    transition_to_state: true
  - outcome: preemption
    transition: preemption
    transition_to_state: false
  - outcome: normal
    transition: "[next_task_name]"
    transition_to_state: true
type: gas_inspection_behavior_plugins::InspectAreaFromPose""",
    Loader=yaml.FullLoader,
)


def set_next_task_name(task, next_task_name):
    for transition in task["transitions"]:
        if transition["transition"] == "[next_task_name]":
            transition["transition"] = next_task_name


def set_last_task_transitions(task):
    for transition in task["transitions"]:
        if transition["transition"] == "[next_task_name]":
            transition["transition_to_state"] = False
            if transition["outcome"] == "success" or transition["outcome"] == "normal":
                transition["transition"] = "success"
            else:
                transition["transition"] = "failure"
