import math
import json


class WorldState:
    def __init__(self, supervisor, proximity_sensors=None):
        self.supervisor = supervisor
        self.proximity_sensors = proximity_sensors or []

        self.state = {"robot": {}, "objects": [], "runtime": {}}

        # Cache static nodes during initialization to save CPU cycles!
        self.cached_targets = []
        self.cached_walls = []
        self._cache_scene_objects()

    # ==================================================
    # CACHING ENGINE (Runs ONCE)
    # ==================================================
    def _cache_scene_objects(self):
        root = self.supervisor.getRoot()
        children = root.getField("children")

        for i in range(children.getCount()):
            node = children.getMFNode(i)
            if not node:
                continue

            node_def = node.getDef()
            if not node_def:
                continue

            if node_def.startswith("TARGET_"):
                self.cached_targets.append({"id": node_def, "node": node})
            elif node_def.startswith("WALL_"):
                # If walls never move, we can just store their static position now
                pos = node.getPosition()
                self.cached_walls.append(
                    {
                        "id": node_def,
                        "type": "wall",
                        "position": [round(pos[0], 3), round(pos[1], 3)],
                    }
                )

    # ==================================================
    # MAIN UPDATE LOOP
    # ==================================================
    def update(self, active_skill=None):
        self.update_robot_state(active_skill)
        self.update_objects()
        self.update_runtime()

    # ==================================================
    # ROBOT STATE
    # ==================================================
    def update_robot_state(self, active_skill=None):
        robot_node = self.supervisor.getSelf()
        position = robot_node.getPosition()
        orientation = robot_node.getOrientation()
        heading = math.atan2(orientation[3], orientation[0])

        # Grab sensor data
        sensor_data = []
        for sensor in self.proximity_sensors:
            try:
                sensor_data.append(round(sensor.getValue(), 1))
            except Exception:
                sensor_data.append(0.0)

        self.state["robot"] = {
            "position": [round(position[0], 3), round(position[1], 3)],
            "heading": round(heading, 3),
            "sensors": sensor_data,
            "active_skill": active_skill.__class__.__name__ if active_skill else "None",
        }

    # ==================================================
    # OBJECT TRACKING
    # ==================================================
    def update_objects(self):
        objects = []

        # 1. Add static walls directly from cache (No Webots API calls needed!)
        objects.extend(self.cached_walls)

        # 2. Update target positions (in case they are moving targets)
        for target in self.cached_targets:
            pos = target["node"].getPosition()
            objects.append(
                {
                    "id": target["id"],
                    "type": "target",
                    "position": [round(pos[0], 3), round(pos[1], 3)],
                }
            )

        self.state["objects"] = objects

    # ==================================================
    # RUNTIME INFO
    # ==================================================
    def update_runtime(self):
        self.state["runtime"] = {
            # Use simulation time, not OS time
            "timestamp": round(self.supervisor.getTime(), 2),
            "object_count": len(self.state["objects"]),
        }

    # ==================================================
    # PUBLIC ACCESSORS
    # ==================================================
    def get_state(self):
        return self.state

    def to_json(self):
        return json.dumps(self.state)
