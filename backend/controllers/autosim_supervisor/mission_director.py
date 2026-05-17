import json


class MissionDirector:
    def __init__(self, blackboard, llm_client, sio=None):
        self.blackboard = blackboard
        self.llm_client = llm_client
        self.sio = sio

    # MAIN ENTRY
    def generate_objectives(self, agent_id):
        snapshot = self.blackboard.snapshot()
        mission = snapshot["mission"]
        semantic = snapshot["semantic_state"]
        prompt = self.build_prompt(mission, semantic)
        response = self.llm_client.generate(prompt)
        objectives = self.parse_response(response)

        self.blackboard.set_objectives(agent_id, objectives)
        self.blackboard.set_current_objective(
            agent_id, objectives[0] if objectives else None
        )
        self.log(f"[{agent_id}] Generated {len(objectives)} mission objectives.")
        return objectives

    # PROMPT
    def build_prompt(self, mission, semantic):
        return f"""
            You are a robotics mission strategist.

            Your job:
            Convert the user goal into
            high-level mission objectives.

            USER GOAL:
            {mission["user_goal"]}

            SEMANTIC WORLD STATE:
            {json.dumps(semantic, indent=2)}

            RULES:
            - Output ONLY JSON
            - Do NOT explain
            - Do NOT generate robot skills
            - Objectives should be strategic

            FORMAT:

            {{
                "objectives": [
                    "Scan nearby environment",
                    "Navigate to TARGET_0",
                    "Patrol perimeter"
                ]
            }}
            """

    # PARSING

    def parse_response(self, response):

        try:

            data = json.loads(response)

            return data.get("objectives", [])

        except Exception as e:

            self.log(f"Failed to parse objectives: {e}")

            return []

    # LOGGING

    def log(self, message):

        if self.sio:

            self.sio.emit("agent_log", {"agent": "Strategist", "message": message})
