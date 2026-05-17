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

        robot_type = snapshot.get("robots", {}).get(agent_id, {}).get("type", "ground")
        recon_complete = semantic.get("recon_complete", False)

        if robot_type == "ground" and not recon_complete:
            self.log(
                f"[{agent_id.upper()}] Awaiting aerial intelligence before dispatching ground units..."
            )

            self.blackboard.set_objectives(agent_id, [])
            self.blackboard.set_current_objective(agent_id, None)
            return []

        if mission.get("dispatched", {}).get(agent_id, False):
            return []  # Already planned!

        all_robots = snapshot.get("robots", {})
        ground_swarm = [
            rid for rid, data in all_robots.items() if data.get("type") == "ground"
        ]
        discovered_targets = semantic.get("discovered_targets", [])

        # If the drone found nothing, just explore
        if not discovered_targets:
            self.log(
                f"[{agent_id.upper()}] No targets found. Defaulting to exploration."
            )
            fallback = ["Explore the environment"]
            self.blackboard.set_objectives(agent_id, fallback)
            self.blackboard.set_current_objective(agent_id, fallback[0])
            self.blackboard.state["mission"]["dispatched"][agent_id] = True
            return fallback

        self.log(
            f"[{agent_id.upper()}] Targets acquired from Aerial Feed. Computing optimal swarm distribution..."
        )
        prompt = self.build_prompt(mission, discovered_targets, ground_swarm)
        response = self.llm_client.generate(prompt)
        swarm_allocation = self.parse_response(response)
        my_objectives = swarm_allocation.get(agent_id, [])

        if not my_objectives:
            my_objectives = ["Patrol the environment to assist swarm"]

        self.blackboard.set_objectives(agent_id, my_objectives)
        self.blackboard.set_current_objective(agent_id, my_objectives[0])
        self.blackboard.state["mission"]["dispatched"][agent_id] = True
        self.log(
            f"[{agent_id.upper()}] Task assignments deployed to ground swarm: {my_objectives}"
        )
        return my_objectives

    # PROMPT
    def build_prompt(self, mission, discovered_targets, ground_swarm):
        target_summaries = [t["id"] for t in discovered_targets]

        # DYNAMIC SCALING: Build the JSON template based on however many robots actually exist!
        dynamic_json_example = {}
        for robot_id in ground_swarm:
            dynamic_json_example[robot_id] = [f"Tactical objective for {robot_id}"]

        return f"""
            You are the Swarm Strategist for a multi-agent robotics system.

            USER COMMAND:
            "{mission["user_goal"]}"

            AERIAL RECON DATA:
            Discovered Targets: {target_summaries}

            ACTIVE GROUND UNITS (SWARM):
            {ground_swarm}

            YOUR STRATEGIC DIRECTIVE:
            1. Analyze the USER COMMAND. This is your ultimate law.
            2. Distribute tasks among the ACTIVE GROUND UNITS to fulfill the command.
            3. DIVISION OF LABOR: Unless the user explicitly asks them to group up, DO NOT assign the same target to multiple robots! Divide the targets fairly.
            4. ROLE ALLOCATION: If the User Command assigns specific roles (e.g., "Robot 1 guards, Robot 2 explores"), you must obey that logic.
            5. Assign high-level tactical objectives (e.g., "Navigate to TARGET_0"), NOT low-level motor skills.

            RULES:
            - Output strictly valid JSON.
            - Every ground unit listed in the ACTIVE GROUND UNITS array MUST have a corresponding key in the JSON output.

            REQUIRED JSON FORMAT:
            {json.dumps(dynamic_json_example, indent=4)}
            """

    # PARSING

    def parse_response(self, response):
        try:
            cleaned = response.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned)
        except Exception as e:
            self.log(f"Failed to parse swarm objectives: {e}. Raw: {response}")
            return {}

    # LOGGING

    def log(self, message):
        if self.sio:
            self.sio.emit("agent_log", {"agent": "Strategist", "message": message})
