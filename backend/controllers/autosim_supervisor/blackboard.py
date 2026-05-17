import json
import copy


class Blackboard:

    def __init__(self, supervisor):
        self.supervisor = supervisor

        self.state = {
            "mission": {
                "user_goal": None,
                "status": "idle",
                "objectives": {},
                "current_objectives": {},
                "dispatched": {},
            },
            # GLOBAL SEMANTIC STATE
            "semantic_state": {
                "identified_objects": [],
                "dynamic_obstacles": [],
                "danger_zones": [],
                "reachable_targets": [],
                "discovered_targets": [],
            },
            # PER-AGENT EXECUTION STATE
            "execution": {
                "execution_states": {},
                "active_plans": {},
                "current_skills": {},
                "skill_queues": {},
                "last_completed_skills": {},
            },
            # PER-AGENT MEMORY
            "memory": {
                "visited_locations": {},
                "failed_paths": {},
                "event_logs": {},
                "mission_history": [],
            },
            # PER-AGENT ROBOT STATE
            "robots": {},
            # GLOBAL RUNTIME
            "runtime": {"last_update": round(self.supervisor.getTime(), 2), "tick": 0},
            # RAW WORLD STATE
            "world_state": {},
        }

    # AGENT REGISTRATION
    def register_agent(self, agent_id, agent_type="ground"):
        # Mission state
        self.state["mission"]["objectives"][agent_id] = []
        self.state["mission"]["current_objectives"][agent_id] = None
        self.state["mission"]["dispatched"][agent_id] = False

        # Robot state
        self.state["robots"][agent_id] = {
            "type": agent_type,
            "position": None,
            "heading": None,
            "status": "idle",
        }

        # Execution state
        self.state["execution"]["execution_states"][agent_id] = "IDLE"
        self.state["execution"]["active_plans"][agent_id] = []
        self.state["execution"]["current_skills"][agent_id] = None
        self.state["execution"]["skill_queues"][agent_id] = []
        self.state["execution"]["last_completed_skills"][agent_id] = None

        # Memory
        self.state["memory"]["visited_locations"][agent_id] = []
        self.state["memory"]["failed_paths"][agent_id] = []
        self.state["memory"]["event_logs"][agent_id] = []

    # MISSION MANAGEMENT
    def set_user_goal(self, goal):
        self.state["mission"]["user_goal"] = goal

    def set_objectives(self, agent_id, objectives):  # CHANGED: Takes agent_id
        self.state["mission"]["objectives"][agent_id] = objectives

    def set_current_objective(self, agent_id, objective):  # CHANGED: Takes agent_id
        self.state["mission"]["current_objectives"][agent_id] = objective

    def set_mission_status(self, status):
        self.state["mission"]["status"] = status

    # SEMANTIC STATE

    def add_identified_object(self, obj):
        self.state["semantic_state"]["identified_objects"].append(obj)

    def add_dynamic_obstacle(self, obstacle):
        self.state["semantic_state"]["dynamic_obstacles"].append(obstacle)

    def add_reachable_target(self, target):
        self.state["semantic_state"]["reachable_targets"].append(target)

    def add_discovered_target(self, target):
        discovered = self.state["semantic_state"]["discovered_targets"]
        if target not in discovered:
            discovered.append(target)

    # EXECUTION STATE

    def update_execution_state(self, agent_id, state):
        self.state["execution"]["execution_states"][agent_id] = state

    def set_active_plan(self, agent_id, plan):
        self.state["execution"]["active_plans"][agent_id] = plan

    def set_skill_queue(self, agent_id, queue):
        self.state["execution"]["skill_queues"][agent_id] = queue

    def set_current_skill(self, agent_id, skill_name):
        self.state["execution"]["current_skills"][agent_id] = skill_name

    def set_last_completed_skill(self, agent_id, skill_name):
        self.state["execution"]["last_completed_skills"][agent_id] = skill_name

    # MEMORY SYSTEM

    def remember_location(self, agent_id, position):
        self.state["memory"]["visited_locations"][agent_id].append(
            {"position": position, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    def remember_failed_path(self, agent_id, path_data):
        self.state["memory"]["failed_paths"][agent_id].append(
            {"data": path_data, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    def remember_event(self, agent_id, event):
        self.state["memory"]["event_logs"][agent_id].append(
            {"event": event, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    def remember_mission(self, mission):
        self.state["memory"]["mission_history"].append(
            {"mission": mission, "timestamp": round(self.supervisor.getTime(), 2)}
        )

    # ROBOT STATE

    def update_robot_state(self, agent_id, position=None, heading=None, status=None):
        robot = self.state["robots"][agent_id]
        if position is not None:
            robot["position"] = position
        if heading is not None:
            robot["heading"] = heading
        if status is not None:
            robot["status"] = status

    # WORLD STATE
    def set_world_state(self, world_state):
        self.state["world_state"] = world_state

    # RUNTIME

    def increment_tick(self):
        self.state["runtime"]["tick"] += 1
        self.state["runtime"]["last_update"] = round(self.supervisor.getTime(), 2)

    # ACCESSORS

    def get_state(self):
        return self.state

    def snapshot(self):
        return copy.deepcopy(self.state)

    def to_json(self):
        return json.dumps(self.snapshot())
