from skills import SpinScanSkill, WanderSkill, GoToTargetSkill, PatrolSkill

class PlanExecutor:
    def __init__(self, supervisor, sio, hardware_map):
        self.supervisor = supervisor
        self.sio = sio
        self.hardware_map = hardware_map
        
        self.plan_queue = []
        self.current_skill = None
        self.status = "IDLE" # IDLE, RUNNING, DONE, FAILED

    def load_plan(self, plan_dict):
        """Loads a validated JSON plan from the Planner."""
        self.plan_queue = plan_dict.get("plan", [])
        self.current_skill = None
        self.status = "RUNNING" if self.plan_queue else "IDLE"
        
        if self.sio:
            self.sio.emit("agent_log", {"agent": "Executor", "message": f"Loaded new plan with {len(self.plan_queue)} steps."})

    def update(self):
        """Called every physics tick."""
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
                print(f"[Executor] Skill {self.current_skill.__class__.__name__} FAILED.")
                self.abort() # Clear the rest of the plan
                self.status = "FAILED"
                return self.status
            
            self.current_skill.stop()
            self.current_skill = None
            return "RUNNING" # Still running the overall plan

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

    def _instantiate_next_skill(self):
        """The Factory: Converts JSON steps to Python objects."""
        step = self.plan_queue.pop(0)
        skill_name = step.get("skill")
        params = step.get("parameters", {})
        reason = step.get("reason", "No reason provided")

        if self.sio:
            self.sio.emit("agent_log", {"agent": "Executor", "message": f"Executing: {skill_name} | Reason: {reason}"})

        # --- THE SKILL FACTORY ---
        if skill_name == "SpinScanSkill":
            self.current_skill = SpinScanSkill(
                self.supervisor, self.sio, 
                self.hardware_map["left_motor"], self.hardware_map["right_motor"],
                duration_ticks=params.get("duration", 100)
            )

        elif skill_name == "WanderSkill":
            self.current_skill = WanderSkill(
                self.supervisor, self.sio, 
                self.hardware_map["left_motor"], self.hardware_map["right_motor"],
                self.hardware_map["proximity_sensors"]
            )

        elif skill_name == "GoToTargetSkill":
            # We must find the specific target node the LLM asked for
            target_id = params.get("target_id")
            target_node = self.supervisor.getFromDef(target_id)
            
            if not target_node:
                print(f"[Executor] ERROR: Target {target_id} not found in world!")
                self.abort()
                self.status = "FAILED"
                return

            self.current_skill = GoToTargetSkill(
                self.supervisor, self.sio, 
                self.hardware_map["left_motor"], self.hardware_map["right_motor"],
                target_node=target_node
            )
        
        elif skill_name == "PatrolSkill":
            # Assuming the LLM JSON passes: "parameters": {"waypoints": ["TARGET_0", "TARGET_1"]}
            waypoint_ids = params.get("waypoints", [])
            
            # Fetch the actual Webots nodes from the strings
            waypoint_nodes = [self.supervisor.getFromDef(wid) for wid in waypoint_ids]
            
            # Filter out any None values in case the LLM hallucinated a bad target ID
            waypoint_nodes = [n for n in waypoint_nodes if n is not None]

            if not waypoint_nodes:
                print("[Executor] ERROR: PatrolSkill received no valid waypoints.")
                self.abort()
                self.status = "FAILED"
                return

            self.current_skill = PatrolSkill(
                self.supervisor, self.sio, 
                self.hardware_map["left_motor"], self.hardware_map["right_motor"],
                waypoint_nodes=waypoint_nodes,
                goto_skill_class=GoToTargetSkill # Notice we pass the Class, not an instance!
            )
            
        self.current_skill.start()