import math
from langchain_core.tools import tool
from pathfinder import AStarPathfinder
import json


# ==========================================
# TOOL 1: PATHFINDING (Tactical Checking)
# ==========================================
@tool
def check_path_feasibility(
    start_x: float, start_y: float, target_x: float, target_y: float, obstacles: list
) -> str:
    """
    Checks if a physical path exists from the robot's location to the target.
    Always use this tool to verify a route is not blocked by walls before dispatching a GoToTarget action.
    Returns the path feasibility and estimated distance.
    """
    # Instantiate your existing class under the hood
    pathfinder = AStarPathfinder(cell_size=0.1, obstacle_padding=0.25)

    start_pos = (start_x, start_y)
    target_pos = (target_x, target_y)

    # Run the math
    path = pathfinder.find_path(start_pos, target_pos, obstacles)

    if not path:
        return "CRITICAL: Path is blocked. Target is physically unreachable. Replan required."

    return f"Path is clear. Route requires {len(path)} steps."


# ==========================================
# TOOL 2: SPATIAL AWARENESS (Perception Math)
# ==========================================
@tool
def calculate_spatial_relationship(
    robot_x: float, robot_y: float, target_x: float, target_y: float
) -> str:
    """
    Calculates the physical distance and compass quadrant of an object relative to the robot.
    Use this to understand which direction to look or travel.
    """
    dx = target_x - robot_x
    dy = target_y - robot_y
    distance = round(math.sqrt(dx**2 + dy**2), 2)

    # Your quadrant logic
    if dx >= 0 and dy >= 0:
        quadrant = "North-East"
    elif dx < 0 and dy >= 0:
        quadrant = "North-West"
    elif dx < 0 and dy < 0:
        quadrant = "South-West"
    else:
        quadrant = "South-East"

    return f"Target is {distance} meters away in the {quadrant} quadrant."


# ==========================================
# TOOL 3: ACTION DISPATCHER
# ==========================================
@tool
def dispatch_physical_action(
    skill_name: str, agent_id: str, target_id: str = None, leader_id: str = None
) -> str:
    """
    Use this tool when you have made your final decision on what physical action to take.
    Valid skill_names: 'GoToTargetSkill', 'WanderSkill', 'FollowLeaderSkill', 'AvoidObstacleSkill', 'SpinScanSkill'.
    If GoToTargetSkill, provide target_id. If FollowLeaderSkill, provide leader_id.
    """

    payload = {"agent_id": agent_id, "plan": [{"skill": skill_name, "parameters": {}}]}

    if target_id:
        payload["plan"][0]["parameters"]["target_id"] = target_id
    if leader_id:
        payload["plan"][0]["parameters"]["leader_id"] = leader_id
    return f"ACTION_LOCKED: {json.dumps(payload)}"
