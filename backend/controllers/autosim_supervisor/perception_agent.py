import math


class PerceptionAgent:

    def __init__(self, blackboard, sio=None):

        self.blackboard = blackboard
        self.sio = sio
        self.last_summary = ""

    # MAIN UPDATE
    def update(self):
        snapshot = self.blackboard.snapshot()
        robot = snapshot["robot"]
        semantic_objects = []
        blocked_zones = []
        robot_position = robot.get("position")

        if not robot_position:
            return
    
        objects = snapshot.get("world_state", {}).get("objects", [])

        for obj in objects:
            semantic = self.interpret_object(robot_position, obj)
            semantic_objects.append(semantic)
            if obj["type"] == "wall":
                blocked_zones.append(semantic["quadrant"])

        semantic_state = {
            "identified_objects": semantic_objects,
            "blocked_quadrants": list(set(blocked_zones)),
            "summary": self.generate_summary(semantic_objects, blocked_zones),
        }

        self.blackboard.state["semantic_state"] = semantic_state
        if semantic_state["summary"] != self.last_summary:
            self.log(semantic_state["summary"])
            self.last_summary = semantic_state["summary"]

    # ==================================================
    # OBJECT INTERPRETATION
    # ==================================================

    def interpret_object(self, robot_position, obj):

        obj_pos = obj["position"]

        dx = obj_pos[0] - robot_position[0]
        dy = obj_pos[1] - robot_position[1]

        quadrant = self.determine_quadrant(dx, dy)
        distance = math.sqrt(dx**2 + dy**2)

        return {
            "id": obj["id"],
            "type": obj["type"],
            "quadrant": quadrant,
            "distance": round(distance, 2),
            "position": obj_pos,
        }

    # QUADRANT CLASSIFICATION

    def determine_quadrant(self, dx, dy):
        if dx >= 0 and dy >= 0: return "North-East"
        elif dx < 0 and dy >= 0: return "North-West"
        elif dx < 0 and dy < 0: return "South-West"
        return "South-East"

    # SEMANTIC SUMMARY

    def generate_summary(self, objects, blocked):
        targets = [o for o in objects if o["type"] == "target"]
        walls = [o for o in objects if o["type"] == "wall"]
        summary = f"Detected {len(targets)} targets " f"and {len(walls)} walls. "

        if blocked:
            summary += "Blocked regions detected in: " + ", ".join(set(blocked))
        else:
            summary += "All regions appear navigable."
        return summary

    # LOGGING
    def log(self, message):

        if self.sio:

            self.sio.emit("agent_log", {"agent": "Oracle", "message": message})
