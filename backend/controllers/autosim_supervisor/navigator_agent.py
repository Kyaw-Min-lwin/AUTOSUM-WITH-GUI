import json
import re

AVAILABLE_SKILLS = {
    "SpinScanSkill": {
        "description": "Rotate in place and scan the environment.",
        "params": ["duration_seconds"], # CHANGED
    },
    "WanderSkill": {
        "description": "Move randomly through the environment.",
        "params": ["duration_seconds"], # CHANGED
    },
    "GoToTargetSkill": {
        "description": "Navigate toward a known target object.",
        "params": ["target_id"],
    },
    "PatrolSkill": {
        "description": "Continuously patrol through waypoints.",
        "params": [],
    },
}

class NavigatorAgent:
    def __init__(self, llm_client, pathfinder, max_retries=3, sio=None):
        self.llm_client = llm_client
        self.pathfinder = pathfinder
        self.max_retries = max_retries
        self.sio = sio

    # ==================================================
    # MAIN PIPELINE
    # ==================================================
    def generate_plan(self, blackboard_snapshot):
        # 1. Read context from the Blackboard
        mission = blackboard_snapshot.get("mission", {})
        current_objective = mission.get("current_objective")
        semantic_state = blackboard_snapshot.get("semantic_state", {})
        memory = blackboard_snapshot.get("memory", {})
        robot = blackboard_snapshot.get("robot", {})
        world_state = blackboard_snapshot.get("world_state", {})

        if not current_objective:
            return {"plan": [], "confidence": 0.0}

        # 2. Tool Use: Pre-validate reachable targets using deterministic A*
        reachable_targets = self._compute_reachable_targets(robot, world_state)

        # 3. Build the tactical prompt
        prompt = self.build_prompt(
            current_objective, semantic_state, memory, reachable_targets
        )

        # 4. LLM Query & Validation Loop
        for attempt in range(self.max_retries):
            try:
                if self.sio:
                    self.sio.emit(
                        "agent_log",
                        {
                            "agent": "Navigator",
                            "message": "Evaluating tactical permutations...",
                        },
                    )

                response = self.query_llm(prompt)
                plan_dict = self.parse_response(response)

                # Validate the plan against physical constraints
                validated_plan = self.validate_plan(plan_dict, reachable_targets)

                if self.sio:
                    conf = validated_plan.get("confidence", 0.0)
                    self.sio.emit(
                        "agent_log",
                        {
                            "agent": "Navigator",
                            "message": f"Tactical plan secured. (Confidence: {conf*100}%)",
                        },
                    )

                return validated_plan

            except Exception as e:
                print(f"[Navigator] Attempt {attempt + 1} failed: {e}")
                prompt += (
                    f"\n\nSystem Error on previous attempt: {e}. Please fix the JSON."
                )

        # 5. Fallback
        print("[Navigator] CRITICAL: LLM failed to generate a valid plan.")
        return {
            "confidence": 0.1,
            "plan": [
                {
                    "skill": "WanderSkill",
                    "parameters": {},
                    "reason": "Fallback due to planning failure.",
                }
            ],
        }

    # ==================================================
    # DETERMINISTIC TOOL CAPABILITIES
    # ==================================================
    def _compute_reachable_targets(self, robot, world_state):
        """Uses the A* Pathfinder to filter out targets trapped behind walls."""
        robot_pos = robot.get("position")
        if not robot_pos:
            return []

        objects = world_state.get("objects", [])
        walls = [o["position"] for o in objects if o["type"] == "wall"]
        targets = [o for o in objects if o["type"] == "target"]

        reachable = []
        for t in targets:
            # We use A* to check if a path physically exists
            path = self.pathfinder.find_path(robot_pos, t["position"], walls)
            if path:  # If path is not empty, it's reachable
                reachable.append(t["id"])

        return reachable

    # ==================================================
    # PROMPT ENGINEERING
    # ==================================================
    def build_prompt(
        self, current_objective, semantic_state, memory, reachable_targets
    ):
        skill_descriptions = [
            f"- {k}: {v['description']} (Requires: {v['params']})"
            for k, v in AVAILABLE_SKILLS.items()
        ]

        # Extract failed events to prevent looping mistakes
        recent_failures = memory.get("event_log", [])[-3:]

        return f"""
You are the Navigator Agent of an autonomous robotics system.
Your job is to compose a feasible tactical route using verified capabilities to achieve the CURRENT OBJECTIVE.

CURRENT OBJECTIVE:
"{current_objective}"

AVAILABLE SKILLS:
{chr(10).join(skill_descriptions)}

ENVIRONMENTAL CONTEXT:
Semantic State: {json.dumps(semantic_state, indent=2)}
Physically Reachable Targets: {reachable_targets}

RECENT FAILURES (Do not repeat these mistakes):
{json.dumps(recent_failures, indent=2)}

RULES:
- ONLY use available skills.
- NEVER target an ID that is not in the Physically Reachable Targets list.
- Provide a confidence score (0.0 to 1.0) based on target reachability and obstacles.
- Output ONLY valid JSON. No conversational text.

FORMAT:
{{
  "confidence": 0.95,
  "plan": [
    {{
      "skill": "SkillName",
      "parameters": {{}},
      "reason": "why this step exists"
    }}
  ]
}}
"""

    def query_llm(self, prompt):
        return self.llm_client.generate(prompt)

    def parse_response(self, response):
        try:
            cleaned = re.sub(r"```[a-zA-Z]*\n", "", response)
            cleaned = re.sub(r"```", "", cleaned).strip()
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to decode JSON. Raw response: {response}")

    def validate_plan(self, plan, reachable_targets):
        if not isinstance(plan, dict) or "plan" not in plan:
            raise Exception("JSON is missing the root 'plan' array.")

        validated_steps = []
        for step in plan["plan"]:
            skill_name = step.get("skill")
            if skill_name not in AVAILABLE_SKILLS:
                raise Exception(f"Hallucinated skill: {skill_name}")

            required_params = AVAILABLE_SKILLS[skill_name]["params"]
            provided_params = step.get("parameters", {})

            for req in required_params:
                if req not in provided_params:
                    raise Exception(
                        f"Skill '{skill_name}' is missing required parameter '{req}'"
                    )

            # STRICT FEASIBILITY VALIDATION
            if skill_name == "GoToTargetSkill":
                target_id = provided_params.get("target_id")
                if target_id not in reachable_targets:
                    raise Exception(
                        f"Target '{target_id}' is physically unreachable or hallucinated!"
                    )

            validated_steps.append(step)

        # Preserve the confidence score
        return {"confidence": plan.get("confidence", 0.5), "plan": validated_steps}
