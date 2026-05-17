import math


class PerceptionAgent:

    def __init__(self, blackboard, sio=None):

        self.blackboard = blackboard
        self.sio = sio
        self.last_summary = ""

    # MAIN UPDATE
    def update(self, agent_id):
        snapshot = self.blackboard.snapshot()
        robot = snapshot.get("robots", {}).get(agent_id, {})
        robot_position = robot.get("position")
        if not robot_position:
            return
        semantic_objects = []
        blocked_zones = []
        objects = snapshot.get("world_state", {}).get("objects", [])

        for obj in objects:
            semantic = self.interpret_object(robot_position, obj)
            semantic_objects.append(semantic)
            if obj["type"] == "wall":
                blocked_zones.append(semantic["quadrant"])

        recon_status = self.blackboard.state["semantic_state"].get("recon_complete", False)
        semantic_state = {
            "identified_objects": semantic_objects,
            "blocked_quadrants": list(set(blocked_zones)),
            "summary": self.generate_summary(semantic_objects, blocked_zones),
            "recon_complete": recon_status,
            "discovered_targets": self.blackboard.state["semantic_state"].get("discovered_targets", [])
        }

        self.blackboard.state["semantic_state"] = semantic_state
        if semantic_state["summary"] != self.last_summary:
            self.log(f"[{agent_id.upper()}] {semantic_state['summary']}")
            self.last_summary = semantic_state["summary"]

    # AERIAL RECON TRIGGER
    def check_aerial_recon(self, blackboard, supervisor, drone_id="drone_1"):
        """Watches the drone altitude and unlocks the map for the swarm."""
        # 1. If already did the recon, do nothing.
        if blackboard.state["semantic_state"].get("recon_complete", False):
            return

        # 2. Grab the drone node
        drone_node = supervisor.getFromDef(drone_id.upper())
        if not drone_node:
            return

        # 3. Check Z-coordinate (Altitude in Webots ENU)
        altitude = drone_node.getPosition()[2]

        # 4. THE TRIGGER
        if altitude >= 2.8:
            targets_found = 0
            
            # Query the Webots tree dynamically
            root = supervisor.getRoot()
            children = root.getField("children")
            
            for i in range(children.getCount()):
                node = children.getMFNode(i)
                if node and node.getDef() and node.getDef().startswith("TARGET_"):
                    pos = node.getPosition()
                    
                    target_data = {
                        "id": node.getDef(),
                        "type": "target",
                        "position": [round(pos[0], 3), round(pos[1], 3)]
                    }
                    
                    # Write to the global Blackboard memory!
                    blackboard.add_discovered_target(target_data)
                    targets_found += 1

            # Lock the trigger so it doesn't fire again
            blackboard.state["semantic_state"]["recon_complete"] = True

            # 5. THE FLASHY OUTPUT
            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {
                        "agent": "Oracle",
                        "message": f"AERIAL SCAN COMPLETE. {targets_found} TARGETS ACQUIRED. UPLOADING COORDINATES TO SWARM BLACKBOARD."
                    }
                )
                
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
