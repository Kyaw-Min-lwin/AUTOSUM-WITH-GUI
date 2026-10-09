"""Validate executable skills against the authoritative mission snapshot."""
import math
from pydantic import BaseModel, ConfigDict, Field
from .pathfinder import AStarPathfinder

# Match GoToTargetSkill's current geometry settings.
PATH_PADDING = 0.04
SKILLS = {"GoToTargetSkill", "WanderSkill", "SpinScanSkill", "FollowLeaderSkill", "PatrolSkill"}


class SkillStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str
    parameters: dict = Field(default_factory=dict)


def normalize_target_id(target_id):
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("Target IDs must be nonempty strings")
    return target_id.upper()


def reachable(state, agent_id, target_id, start=None):
    target_id = normalize_target_id(target_id)
    objects = state["world_state"]["objects"]
    target = next((o for o in objects if o["id"] == target_id and o["type"] == "target"), None)
    if target is None:
        raise ValueError(f"Unknown target: {target_id}")
    position = start or state["robots"][agent_id]["position"]
    if position is None:
        raise ValueError("Robot position is not available")
    walls = [o["position"] for o in objects if o["type"] == "wall"]
    path = AStarPathfinder(cell_size=.1, obstacle_padding=PATH_PADDING).find_path(
        position, target["position"], walls)
    if not path:
        raise ValueError(f"No route to {target_id}")
    return path


def validate_step(state, agent_id, skill_name, parameters):
    step = SkillStep(skill=skill_name, parameters=parameters).model_dump()
    if skill_name not in SKILLS:
        raise ValueError(f"Unsupported skill: {skill_name}")
    if state["robots"].get(agent_id, {}).get("type") != "ground":
        raise ValueError("Only registered ground robots receive navigation plans")
    params = step["parameters"]
    if skill_name == "PatrolSkill" and "waypoint_ids" in params:
        if "waypoints" in params:
            raise ValueError("Use either waypoints or waypoint_ids, not both")
        params["waypoints"] = params.pop("waypoint_ids")
    allowed = {
        "GoToTargetSkill": {"target_id"}, "FollowLeaderSkill": {"leader_id"},
        "WanderSkill": {"duration_seconds"}, "SpinScanSkill": {"duration_seconds"},
        "PatrolSkill": {"waypoints"},
    }[skill_name]
    if set(params) - allowed:
        raise ValueError(f"Unexpected parameters for {skill_name}")
    if skill_name == "GoToTargetSkill":
        params["target_id"] = normalize_target_id(params.get("target_id"))
        reachable(state, agent_id, params["target_id"])
    elif skill_name == "FollowLeaderSkill":
        leader = params.get("leader_id")
        if leader == agent_id or state["robots"].get(leader, {}).get("type") != "ground":
            raise ValueError("leader_id must identify another ground robot")
    elif skill_name == "PatrolSkill":
        points = params.get("waypoints")
        if not isinstance(points, list) or not points:
            raise ValueError("Patrol requires nonempty waypoints")
        points = [normalize_target_id(target) for target in points]
        params["waypoints"] = points
        start = None
        for target in points + points[:1]:
            path = reachable(state, agent_id, target, start)
            start = path[-1]
    else:
        seconds = params.setdefault("duration_seconds", 5.0)
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or not 0 < seconds <= 300):
            raise ValueError("duration_seconds must be between 0 and 300")
    return step
