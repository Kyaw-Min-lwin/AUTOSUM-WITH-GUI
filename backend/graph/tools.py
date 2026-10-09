import json
import math
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .actions import reachable, validate_step


@tool
def check_path_feasibility(target_id: str, state: Annotated[dict, InjectedState]) -> str:
    """Check a target's route using the robot position and walls from mission telemetry."""
    path = reachable(state["swarm"], state["agent_id"], target_id)
    return f"Path is clear: {len(path)} waypoints."


@tool
def calculate_spatial_relationship(target_id: str, state: Annotated[dict, InjectedState]) -> str:
    """Get distance and bearing to a known target from authoritative world coordinates."""
    swarm = state["swarm"]
    target = next((o for o in swarm["world_state"]["objects"] if o["id"] == target_id), None)
    if target is None:
        raise ValueError("Unknown target")
    position = swarm["robots"][state["agent_id"]]["position"]
    dx, dy = target["position"][0] - position[0], target["position"][1] - position[1]
    return f"Distance {math.hypot(dx, dy):.3f}m; bearing {math.atan2(dy, dx):.3f} radians."


@tool
def dispatch_physical_action(skill_name: str, parameters: dict,
                             state: Annotated[dict, InjectedState]) -> str:
    """Commit ONE validated action for this objective.
    Skills: GoToTargetSkill(target_id), FollowLeaderSkill(leader_id),
    WanderSkill(duration_seconds), SpinScanSkill(duration_seconds),
    PatrolSkill(waypoints: list of target IDs; waypoint_ids is also accepted).
    Use parameters as a JSON object. Patrol repeats until stopped.
    """
    step = validate_step(state["swarm"], state["agent_id"], skill_name, parameters)
    return "ACTION_LOCKED: " + json.dumps({"agent_id": state["agent_id"], "plan": [step]})


navigator_tools = [check_path_feasibility, calculate_spatial_relationship, dispatch_physical_action]
