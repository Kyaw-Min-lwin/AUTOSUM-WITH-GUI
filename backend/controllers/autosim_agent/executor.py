from skills import (
    SpinScanSkill,
    WanderSkill,
    GoToTargetSkill,
    PatrolSkill,
    AerialScanSkill,
    FollowLeaderSkill,
)

class PlanExecutor:

    def __init__(self, agent_id, supervisor, sio, hardware_map):
        self.agent_id = agent_id
        self.supervisor = supervisor
        self.sio = sio
        self.hardware_map = hardware_map

        self.plan_queue = []
        self.current_skill = None
        self.status = "IDLE"

        # AUTO-DEPLOY DRONE BYPASS
        if "drone" in self.agent_id.lower():
            self.plan_queue = [
                {
                    "skill": "AerialScanSkill",
                    "parameters": {},
                    "reason": "Auto-deployed pre-mission intelligence.",
                }
            ]
            self.status = "RUNNING"

            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {
                        "agent": self.agent_id,
                        "message": "Auto-deploying AerialScanSkill for pre-mission intelligence.",
                    },
                )

    def load_plan(self, plan_dict):
        """Loads a validated JSON plan from the Planner."""
        self.plan_queue = plan_dict.get("plan", [])
        self.current_skill = None
        self.status = "RUNNING" if self.plan_queue else "IDLE"

        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": f"Loaded new plan with {len(self.plan_queue)} steps.",
                },
            )

    def update(self):
        """Called every physics tick."""
        if self.status != "RUNNING":
            return self.status

        # 1. If no skill is running, load the next one
        if self.current_skill is None:
            if not self.plan_queue:
                self.status = "DONE"
                self._emit_skill_status("DONE")
                return self.status
            self._instantiate_next_skill()

        # 2. Check if current skill finished
        if self.current_skill.is_complete():
            if getattr(self.current_skill, "failed", False):
                print(
                    f"[Executor] Skill {self.current_skill.__class__.__name__} FAILED."
                )
                self.abort()  # Clear the rest of the plan
                self.status = "FAILED"
                self._emit_skill_status("FAILED")
                return self.status

            self.current_skill.stop()
            self.current_skill = None
            return "RUNNING"  # Still running the overall plan

        # 3. Standard update
        self.current_skill.update()
        return "RUNNING"

    def abort(self):
        """Emergency stop and clear queue."""
        if self.current_skill:
            self.current_skill.stop()
        self.current_skill = None
        self.plan_queue = []
        self.status = "IDLE"

    def _emit_skill_status(self, status):
        if self.sio:
            self.sio.emit(
                "skill_status",
                {
                    "agent": self.agent_id,
                    "status": status,
                },
            )

    def _instantiate_next_skill(self):
        """The Factory: Converts JSON steps to Python objects."""
        step = self.plan_queue.pop(0)
        skill_name = step.get("skill")
        params = step.get("parameters", {})
        reason = step.get("reason", "No reason provided")

        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": f"Executing: {skill_name} | Reason: {reason}",
                },
            )

        TIME_STEP = int(self.supervisor.getBasicTimeStep())
        # --- THE SKILL FACTORY ---
        if skill_name == "SpinScanSkill":
            seconds = params.get("duration_seconds", 3.0)
            ticks = int(seconds * (1000.0 / TIME_STEP))

            self.current_skill = SpinScanSkill(
                agent_id=self.agent_id,
                supervisor=self.supervisor,
                sio=self.sio,
                left_motor=self.hardware_map["left_motor"],
                right_motor=self.hardware_map["right_motor"],
                duration_ticks=ticks,
            )

        elif skill_name == "WanderSkill":
            seconds = params.get("duration_seconds", 10.0)
            ticks = int(seconds * (1000.0 / TIME_STEP))

            self.current_skill = WanderSkill(
                agent_id=self.agent_id,  # <--- ADDED
                supervisor=self.supervisor,
                sio=self.sio,
                left_motor=self.hardware_map["left_motor"],
                right_motor=self.hardware_map["right_motor"],
                proximity_sensors=self.hardware_map["proximity_sensors"],
                duration_ticks=ticks,
            )

        elif skill_name == "GoToTargetSkill":
            target_id = params.get("target_id")
            target_node = self.supervisor.getFromDef(target_id)

            if not target_node:
                print(
                    f"[{self.agent_id} Executor] ERROR: Target {target_id} not found in world!"
                )
                self.abort()
                self.status = "FAILED"
                self._emit_skill_status("FAILED")
                return

            self.current_skill = GoToTargetSkill(
                agent_id=self.agent_id,
                supervisor=self.supervisor,
                sio=self.sio,
                left_motor=self.hardware_map["left_motor"],
                right_motor=self.hardware_map["right_motor"],
                target_node=target_node,
            )

        elif skill_name == "PatrolSkill":
            waypoint_ids = params.get("waypoints", [])
            waypoint_nodes = [self.supervisor.getFromDef(wid) for wid in waypoint_ids]
            waypoint_nodes = [n for n in waypoint_nodes if n is not None]

            if not waypoint_nodes:
                print(
                    f"[{self.agent_id} Executor] ERROR: PatrolSkill received no valid waypoints."
                )
                self.abort()
                self.status = "FAILED"
                self._emit_skill_status("FAILED")
                return

            self.current_skill = PatrolSkill(
                agent_id=self.agent_id,
                supervisor=self.supervisor,
                sio=self.sio,
                left_motor=self.hardware_map["left_motor"],
                right_motor=self.hardware_map["right_motor"],
                waypoint_nodes=waypoint_nodes,
                goto_skill_class=GoToTargetSkill,
            )

        elif skill_name == "AerialScanSkill":
            self.current_skill = AerialScanSkill(
                agent_id=self.agent_id,
                supervisor=self.supervisor,
                sio=self.sio,
                left_motor=None,
                right_motor=None,
            )

        elif skill_name == "FollowLeaderSkill":
            leader_id = params.get("leader_id")
            if not leader_id:
                print(
                    f"[{self.agent_id} Executor] ERROR: FollowLeaderSkill missing leader_id parameter."
                )
                self.abort()
                self.status = "FAILED"
                self._emit_skill_status("FAILED")
                return

            self.current_skill = FollowLeaderSkill(
                agent_id=self.agent_id,
                supervisor=self.supervisor,
                sio=self.sio,
                left_motor=self.hardware_map["left_motor"],
                right_motor=self.hardware_map["right_motor"],
                leader_id=leader_id,
            )

        self.current_skill.start()
