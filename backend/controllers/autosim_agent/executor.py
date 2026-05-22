from skills import (
    SpinScanSkill,
    WanderSkill,
    GoToTargetSkill,
    PatrolSkill,
    AerialScanSkill,
    FollowLeaderSkill,
)
# Import the Pydantic model we defined in the LangGraph setup
from pydantic_models import TacticalPlan, TacticalStep


class PlanExecutor:
    def __init__(self, agent_id, supervisor, sio, hardware_map):
        self.agent_id = agent_id
        self.supervisor = supervisor
        self.sio = sio
        self.hardware_map = hardware_map

        self.plan_queue = []  # Will now hold Pydantic TacticalStep objects
        self.current_skill = None
        self.status = "IDLE"

        # AUTO-DEPLOY DRONE BYPASS
        if "drone" in self.agent_id.lower():
            # We can mock a Pydantic step for the drone's auto-deploy
            self.plan_queue = [
                TacticalStep(
                    skill="AerialScanSkill",
                    parameters={},
                    reason="Auto-deployed pre-mission intelligence."
                )
            ]
            self.status = "RUNNING"
            if self.sio:
                self.sio.emit("agent_log", {
                              "agent": self.agent_id, "message": "Auto-deploying AerialScanSkill."})

    def load_plan(self, plan: TacticalPlan):
        """Loads a strictly validated Pydantic plan from the LangGraph Navigator."""
        self.plan_queue = plan.plan  # This is a List[TacticalStep]
        self.current_skill = None
        self.status = "RUNNING" if self.plan_queue else "IDLE"

        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": f"Loaded new plan with {len(self.plan_queue)} steps. (Confidence: {plan.confidence})",
                },
            )

    def update(self):
        """Called every physics tick by the LangGraph executor_node."""
        if self.status != "RUNNING":
            return self.status

        # 1. If no skill is running, load the next one
        if self.current_skill is None:
            if not self.plan_queue:
                self.status = "DONE"
                return self.status
            self._instantiate_next_skill()

        # 2. Check if current skill finished
        if self.current_skill.is_complete():
            if getattr(self.current_skill, "failed", False):
                print(
                    f"[Executor] Skill {self.current_skill.__class__.__name__} FAILED.")
                self.abort()
                self.status = "FAILED"
                return self.status

            self.current_skill.stop()
            self.current_skill = None
            return "RUNNING"

        # 3. Standard update (Spins the motors in skills.py)
        self.current_skill.update()
        return "RUNNING"

    def abort(self):
        if self.current_skill:
            self.current_skill.stop()
        self.current_skill = None
        self.plan_queue = []
        self.status = "IDLE"

    def _instantiate_next_skill(self):
        """The Factory: Converts Pydantic steps to Python Skill objects."""
        step: TacticalStep = self.plan_queue.pop(0)

        # Because of LangChain/Pydantic, we are 100% guaranteed these exist and are typed correctly!
        skill_name = step.skill
        params = step.parameters
        reason = step.reason

        if self.sio:
            self.sio.emit("agent_log", {
                          "agent": self.agent_id, "message": f"Executing: {skill_name} | Reason: {reason}"})

        TIME_STEP = int(self.supervisor.getBasicTimeStep())

        # --- THE SKILL FACTORY ---
        if skill_name == "SpinScanSkill":
            seconds = params.get("duration_seconds", 3.0)
            ticks = int(seconds * (1000.0 / TIME_STEP))
            self.current_skill = SpinScanSkill(
                self.agent_id, self.supervisor, self.sio,
                self.hardware_map["left_motor"], self.hardware_map["right_motor"], ticks
            )

        elif skill_name == "WanderSkill":
            seconds = params.get("duration_seconds", 10.0)
            ticks = int(seconds * (1000.0 / TIME_STEP))
            self.current_skill = WanderSkill(
                self.agent_id, self.supervisor, self.sio,
                self.hardware_map["left_motor"], self.hardware_map["right_motor"],
                self.hardware_map["proximity_sensors"], duration_ticks=ticks
            )

        elif skill_name == "GoToTargetSkill":
            target_id = params.get("target_id")
            target_node = self.supervisor.getFromDef(target_id)
            if not target_node:
                self.abort()
                self.status = "FAILED"
                return
            self.current_skill = GoToTargetSkill(
                self.agent_id, self.supervisor, self.sio,
                self.hardware_map["left_motor"], self.hardware_map["right_motor"], target_node
            )

        elif skill_name == "PatrolSkill":
            waypoint_ids = params.get("waypoints", [])
            waypoint_nodes = [self.supervisor.getFromDef(
                wid) for wid in waypoint_ids if self.supervisor.getFromDef(wid)]
            if not waypoint_nodes:
                self.abort()
                self.status = "FAILED"
                return
            self.current_skill = PatrolSkill(
                self.agent_id, self.supervisor, self.sio,
                self.hardware_map["left_motor"], self.hardware_map["right_motor"],
                waypoint_nodes, GoToTargetSkill
            )

        elif skill_name == "AerialScanSkill":
            self.current_skill = AerialScanSkill(
                self.agent_id, self.supervisor, self.sio
            )

        elif skill_name == "FollowLeaderSkill":
            leader_id = params.get("leader_id")
            self.current_skill = FollowLeaderSkill(
                self.agent_id, self.supervisor, self.sio,
                self.hardware_map["left_motor"], self.hardware_map["right_motor"], leader_id
            )

        self.current_skill.start()
