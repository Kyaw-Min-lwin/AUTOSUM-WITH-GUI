"""Mission lifecycle; callers hold the application lock around state changes."""
from copy import deepcopy
import math
import re
from uuid import uuid4

from graph.state import create_initial_state, register_agent_patch

RECON_ALTITUDE = 0.8  # Matches AerialScanSkill in the thin controller.
MAX_PLAN_ATTEMPTS = 3


def normalize_map(map_data):
    if not isinstance(map_data, dict):
        raise ValueError("Map must be an object")
    result = {"walls": [], "targets": [], "epucks": [], "drone": None}
    ids = set()

    def position(obj):
        if not isinstance(obj, dict):
            raise ValueError("Map entries must be objects")
        coords = {}
        for axis in ("x", "z"):
            value = obj.get(axis, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Map coordinates must be finite numbers")
            if not -9 <= value <= 9:
                raise ValueError("Place objects inside the arena boundary (-9 to 9)")
            coords[axis] = value
        return coords

    for kind in ("walls", "targets", "epucks"):
        entries = map_data.get(kind, [])
        if not isinstance(entries, list):
            raise ValueError(f"{kind} must be a list")
        for obj in entries:
            item = position(obj)
            if kind == "epucks":
                agent_id = obj.get("id", "")
                if not re.fullmatch(r"epuck_[0-9]+", agent_id) or agent_id in ids:
                    raise ValueError("Ground robot IDs must be unique epuck_<number> names")
                ids.add(agent_id)
                item["id"] = agent_id
            result[kind].append(item)
    if not result["epucks"]:
        result["epucks"] = [{"id": "epuck_1", "x": 0, "z": 0}]
    if map_data.get("drone"):
        result["drone"] = {**position(map_data["drone"]), "id": "drone_1"}
    return result


class MissionCoordinator:
    def __init__(self):
        self.state = create_initial_state()

    def start(self, goal, map_data):
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("Enter a mission goal")
        map_data = normalize_map(map_data)
        self.state = create_initial_state()
        mission = self.state["mission"]
        mission.update(id=uuid4().hex, user_goal=goal.strip(), status="waiting")
        units = [(r["id"], "ground") for r in map_data["epucks"]]
        if map_data["drone"]:
            units.append((map_data["drone"]["id"], "drone"))
        for agent_id, kind in units:
            patch = register_agent_patch(agent_id, kind)
            for key in ("robots", "execution"):
                self.state[key].update(patch[key])
            for key in ("objectives", "dispatched"):
                mission[key].update(patch["mission"][key])
        objects = []
        for kind, prefix in (("walls", "WALL"), ("targets", "TARGET")):
            for i, obj in enumerate(map_data[kind]):
                objects.append({"id": f"{prefix}_{i}", "type": "wall" if kind == "walls" else "target",
                                "position": [round(obj["x"]) * .1, round(obj["z"]) * .1]})
        self.state["world_state"]["objects"] = objects
        # Ground-only missions use the supplied map without waiting for a nonexistent drone.
        if not map_data["drone"]:
            self.state["semantic"] = {
                "recon_complete": True,
                "discovered_targets": [o for o in objects if o["type"] == "target"],
            }
        return deepcopy(map_data), mission["id"]

    def accepts(self, data):
        return (isinstance(data, dict)
                and data.get("mission_id") == self.state["mission"]["id"]
                and data.get("agent_id") in self.state["robots"])

    def telemetry(self, data):
        if not self.accepts(data):
            return False
        agent = self.state["robots"][data["agent_id"]]
        pos = data.get("position")
        if (not isinstance(pos, (list, tuple)) or len(pos) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in pos)):
            return False
        agent.update(position=list(pos), ready=True)
        if agent["type"] == "drone" and pos[2] >= RECON_ALTITUDE:
            self.state["semantic"] = {
                "recon_complete": True,
                "discovered_targets": [
                    o for o in self.state["world_state"]["objects"] if o["type"] == "target"
                ],
            }
        return True

    def needs_planning(self):
        state = self.state
        if state["mission"]["status"] in ("idle", "complete", "failed"):
            return False
        if not state["semantic"]["recon_complete"] or not all(r["ready"] for r in state["robots"].values()):
            return False
        return any(
            r["type"] == "ground" and state["execution"][rid]["status"] == "IDLE"
            and (not state["mission"]["dispatched"][rid] or state["mission"]["objectives"][rid])
            for rid, r in state["robots"].items()
        )

    def snapshot(self):
        snapshot = deepcopy(self.state)
        snapshot["plans"] = {}
        snapshot["planning_errors"] = {}
        return snapshot

    def apply(self, mission_id, result):
        """Merge decisions only; never replace telemetry with an old LLM snapshot."""
        if mission_id != self.state["mission"]["id"]:
            return []
        mission = self.state["mission"]
        patch = result.get("mission", {})
        for rid, objectives in patch.get("objectives", {}).items():
            if rid in mission["objectives"] and not mission["dispatched"][rid]:
                mission["objectives"][rid] = list(objectives)
        mission["dispatched"].update(patch.get("dispatched", {}))
        payloads = []
        for rid, plan in result.get("plans", {}).items():
            execution = self.state["execution"].get(rid)
            if not execution or execution["status"] != "IDLE" or not plan:
                continue
            plan_id = uuid4().hex
            execution.update(status="RUNNING", plan_id=plan_id)
            payloads.append({"mission_id": mission_id, "agent_id": rid, "plan_id": plan_id, "plan": plan})
        for rid, error in result.get("planning_errors", {}).items():
            if rid in self.state["execution"]:
                self.state["execution"][rid].update(status="FAILED", error=error)
        self._update_status()
        return payloads

    def status(self, data):
        if not self.accepts(data):
            return False
        execution = self.state["execution"][data["agent_id"]]
        if not data.get("plan_id") or data["plan_id"] != execution["plan_id"]:
            return False  # Old/duplicate completions cannot advance the next objective.
        status = data.get("status")
        if status not in ("RUNNING", "DONE", "FAILED"):
            return False
        if status == "RUNNING":
            return True
        execution["plan_id"] = None
        if status == "DONE":
            objectives = self.state["mission"]["objectives"][data["agent_id"]]
            if objectives:
                objectives.pop(0)
            execution.update(status="IDLE", attempts=0)
        else:
            execution["attempts"] += 1
            execution["status"] = "IDLE" if execution["attempts"] < MAX_PLAN_ATTEMPTS else "FAILED"
            execution["error"] = data.get("message") or "Physical execution failed"
        self._update_status()
        return True

    def fail(self, mission_id, error):
        if mission_id == self.state["mission"]["id"]:
            self.state["mission"].update(status="failed", error=str(error))

    def _update_status(self):
        ground = [rid for rid, r in self.state["robots"].items() if r["type"] == "ground"]
        if any(self.state["execution"][rid]["status"] == "FAILED" for rid in ground):
            self.state["mission"]["status"] = "failed"
        elif all(self.state["mission"]["dispatched"][rid]
                 and not self.state["mission"]["objectives"][rid]
                 and self.state["execution"][rid]["status"] == "IDLE" for rid in ground):
            self.state["mission"]["status"] = "complete"
        else:
            self.state["mission"]["status"] = "executing"
