import json
import copy


class Blackboard:

    def __init__(self, supervisor):
        self.supervisor = supervisor

        self.state = {
            "mission": {
                "user_goal": None,
                "status": "idle",
                "current_objective": None,
                "objectives": [],
            },
            "semantic_state": {
                "identified_objects": [],
                "dynamic_obstacles": [],
                "danger_zones": [],
                "reachable_targets": [],
            },
            "execution": {
                "active_plan": [],
                "active_skill": None,
                "skill_queue": [],
                "last_completed_skill": None,
            },
            "memory": {
                "visited_locations": [],
                "failed_paths": [],
                "mission_history": [],
                "event_log": [],
            },
            "robot": {"position": None, "heading": None, "status": "idle"},
            "runtime": {"last_update": round(self.supervisor.getTime(), 2), "tick": 0},
            "world_state": {},
        }

    # MISSION MANAGEMENT

    def set_user_goal(self, goal):

        self.state["mission"]["user_goal"] = goal

    def set_objectives(self, objectives):

        self.state["mission"]["objectives"] = objectives

    def set_current_objective(self, objective):

        self.state["mission"]["current_objective"] = objective

    def set_mission_status(self, status):

        self.state["mission"]["status"] = status

    # SEMANTIC STATE

    def add_identified_object(self, obj):
        self.state["semantic_state"]["identified_objects"].append(obj)

    def add_dynamic_obstacle(self, obstacle):
        self.state["semantic_state"]["dynamic_obstacles"].append(obstacle)

    def add_reachable_target(self, target):
        self.state["semantic_state"]["reachable_targets"].append(target)

    # EXECUTION STATE
    def set_active_plan(self, plan):
        self.state["execution"]["active_plan"] = plan

    def set_skill_queue(self, queue):
        self.state["execution"]["skill_queue"] = queue

    def set_active_skill(self, skill_name):
        self.state["execution"]["active_skill"] = skill_name

    def set_last_completed_skill(self, skill_name):
        self.state["execution"]["last_completed_skill"] = skill_name

    # MEMORY SYSTEM

    def remember_location(self, position):
        self.state["memory"]["visited_locations"].append(
            {"position": position, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    def remember_failed_path(self, path_data):
        self.state["memory"]["failed_paths"].append(
            {"data": path_data, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    def remember_event(self, event):
        self.state["memory"]["event_log"].append(
            {"event": event, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    def remember_mission(self, mission):
        self.state["memory"]["mission_history"].append(
            {"mission": mission, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    # ROBOT STATE

    def update_robot_state(self, position=None, heading=None, status=None):

        if position is not None:
            self.state["robot"]["position"] = position

        if heading is not None:
            self.state["robot"]["heading"] = heading

        if status is not None:
            self.state["robot"]["status"] = status

    # RUNTIME
    def increment_tick(self):
        self.state["runtime"]["tick"] += 1
        self.state["runtime"]["last_update"] = round(self.supervisor.getTime(), 2)

    def set_world_state(self, world_state):
        self.state["world_state"] = world_state

    # ACCESSORS

    def get_state(self):

        return self.state

    def snapshot(self):
        """
        Deep copy snapshot for agents.
        Prevents accidental mutation.
        """

        return copy.deepcopy(self.state)

    # ==================================================
    # TELEMETRY FRIENDLY
    # ==================================================

    def to_json(self):

        return json.dumps(self.snapshot())
