import json
import re

AVAILABLE_SKILLS = {
    "SpinScanSkill": {
        "description": "Rotate in place and scan the environment.",
        "params": ["duration"],
    },
    "WanderSkill": {
        "description": "Move randomly through the environment.",
        "params": [],
    },
    "GoToTargetSkill": {
        "description": "Navigate toward a known target object.",
        "params": ["target_id"],  # Be specific: target_id is better than just target
    },
    "PatrolSkill": {
        "description": "Continuously patrol through waypoints.",
        "params": [],
    },
}


class PlannerAgent:
    def __init__(self, llm_client, max_retries=3):
        self.llm_client = llm_client
        self.max_retries = max_retries

    # ==================================================
    # MAIN ENTRY (WITH RETRY LOOP)
    # ==================================================
    def generate_plan(self, user_goal, world_state):
        # Filter out raw sensor floats so the LLM only sees semantic data
        semantic_state = self._filter_semantic_state(world_state)
        prompt = self.build_prompt(user_goal, semantic_state)

        for attempt in range(self.max_retries):
            try:
                response = self.query_llm(prompt)
                plan_dict = self.parse_response(response)
                validated_plan = self.validate_plan(plan_dict)
                return validated_plan

            except Exception as e:
                print(f"[Planner] Attempt {attempt + 1} failed: {e}")
                # Optional: Append the error to the prompt to tell the LLM what it did wrong!
                prompt += (
                    f"\n\nSystem Error on previous attempt: {e}. Please fix the JSON."
                )

        # Fallback if the LLM completely fails
        print(
            "[Planner] CRITICAL: LLM failed to generate a valid plan. Defaulting to Wander."
        )
        return {
            "plan": [
                {
                    "skill": "WanderSkill",
                    "parameters": {},
                    "reason": "Fallback due to planning failure.",
                }
            ]
        }

    # ==================================================
    # PROMPT ENGINEERING
    # ==================================================
    def build_prompt(self, user_goal, semantic_state):
        skill_descriptions = [
            f"- {k}: {v['description']} (Requires: {v['params']})"
            for k, v in AVAILABLE_SKILLS.items()
        ]

        return f"""
                You are the Director Agent of a robotics simulation platform.
                Your job is to create a valid JSON execution plan.

                AVAILABLE SKILLS:
                {chr(10).join(skill_descriptions)}

                CURRENT WORLD STATE:
                {json.dumps(semantic_state, indent=2)}

                USER GOAL:
                "{user_goal}"

                RULES:
                - ONLY use available skills.
                - ONLY output valid JSON. No conversational text.
                - Output format:
                {{
                "plan": [
                    {{
                    "skill": "SkillName",
                    "parameters": {{}},
                    "reason": "why this step exists"
                    }}
                ]
                }}
                """

    # ==================================================
    # LLM QUERY
    # ==================================================

    def query_llm(self, prompt):

        response = self.llm_client.generate(prompt)

        return response

    # ==================================================
    # PARSING
    # ==================================================

    def parse_response(self, response):

        try:
            cleaned = re.sub(r"```[a-zA-Z]*\n", "", response)
            return json.loads(cleaned)

        except json.JSONDecodeError as e:
            raise Exception(f"Failed to decode JSON. Raw response: {response}")

    # ==================================================
    # VALIDATION
    # ==================================================

    def validate_plan(self, plan):
        if not isinstance(plan, dict) or "plan" not in plan:
            raise Exception("JSON is missing the root 'plan' array.")

        validated_steps = []
        for step in plan["plan"]:
            skill_name = step.get("skill")

            # 1. Check if skill exists
            if skill_name not in AVAILABLE_SKILLS:
                raise Exception(f"Hallucinated skill: {skill_name}")

            # 2. Check if required parameters are present
            required_params = AVAILABLE_SKILLS[skill_name]["params"]
            provided_params = step.get("parameters", {})

            for req in required_params:
                if req not in provided_params:
                    raise Exception(
                        f"Skill '{skill_name}' is missing required parameter '{req}'"
                    )

            validated_steps.append(step)

        return {"plan": validated_steps}

    def _filter_semantic_state(self, world_state):
        """Removes low-level physics floats before sending to LLM."""
        filtered = dict(world_state)
        if "robot" in filtered and "sensors" in filtered["robot"]:
            # Delete the raw sensor array from the prompt
            del filtered["robot"]["sensors"]
        return filtered
