from typing import TypedDict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic_models import SwarmAllocation, TacticalPlan


class RobotState(TypedDict):
    agent_id: str
    agent_type: str
    blackboard: Any
    executor: Any
    avoid_skill: Any
    proximity_sensors: list
    pathfinder: Any
    llm: BaseChatModel
    world_tracker: Any
    perception: Any
    supervisor: Any
    evading: bool

# --- NODE 1: PERCEPTION ---


def perception_node(state: RobotState):
    world_tracker = state["world_tracker"]
    executor = state["executor"]
    blackboard = state["blackboard"]
    perception = state["perception"]
    agent_id = state["agent_id"]
    supervisor = state["supervisor"]

    # 1. Raw Physics -> Blackboard
    world_tracker.update(active_skill=executor.current_skill)
    raw_state = world_tracker.get_state()
    blackboard.set_world_state(raw_state)

    blackboard.update_robot_state(
        agent_id,
        position=raw_state["robot"]["position"],
        heading=raw_state["robot"]["heading"],
        status=executor.status,
    )

    # 2. Wake the Oracle
    perception.update(agent_id)
    perception.check_aerial_recon(blackboard, supervisor, agent_id)

    return state

# --- NODE 2: ARBITER (SAFETY OVERRIDE) ---


def is_path_blocked(sensors):
    try:
        if len(sensors) >= 8:
            return (sensors[7].getValue() + sensors[0].getValue()) > 300.0
        return False
    except Exception:
        return False


def arbiter_node(state: RobotState):
    sensors = state["proximity_sensors"]
    avoid_skill = state.get("avoid_skill")

    if avoid_skill and is_path_blocked(sensors):
        avoid_skill.update()
        state["blackboard"].update_robot_state(
            state["agent_id"], status="evading")
        return {"evading": True}

    return {"evading": False}

# --- NODE 3: MISSION DIRECTOR ---


def director_node(state: RobotState):
    agent_id = state["agent_id"]
    blackboard = state["blackboard"]
    llm = state["llm"]

    snapshot = blackboard.snapshot()
    mission = snapshot["mission"]
    semantic = snapshot["semantic_state"]
    robot_type = snapshot.get("robots", {}).get(
        agent_id, {}).get("type", "ground")
    recon_complete = semantic.get("recon_complete", False)

    # Wait for drone
    if robot_type == "ground" and not recon_complete:
        blackboard.set_objectives(agent_id, [])
        blackboard.set_current_objective(agent_id, None)
        return state

    if mission.get("dispatched", {}).get(agent_id, False):
        return state

    ground_swarm = [rid for rid, data in snapshot.get(
        "robots", {}).items() if data.get("type") == "ground"]
    discovered_targets = semantic.get("discovered_targets", [])

    if not discovered_targets:
        fallback = ["Explore the environment"]
        blackboard.set_objectives(agent_id, fallback)
        blackboard.set_current_objective(agent_id, fallback[0])
        blackboard.state["mission"]["dispatched"][agent_id] = True
        blackboard.set_mission_status("needs_planning")
        return state

    # Build Prompt
    target_summaries = [t["id"] for t in discovered_targets]
    prompt = f"""You are the Swarm Strategist.
    USER COMMAND: "{mission['user_goal']}"
    AERIAL RECON DATA: {target_summaries}
    ACTIVE GROUND UNITS: {ground_swarm}
    Distribute tasks fairly among the swarm."""

    # LangChain Structured Output (No more JSON parsing errors!)
    structured_llm = llm.with_structured_output(SwarmAllocation)
    response = structured_llm.invoke(prompt)

    my_objectives = response.allocations.get(
        agent_id, ["Patrol the environment to assist swarm"])

    blackboard.set_objectives(agent_id, my_objectives)
    blackboard.set_current_objective(agent_id, my_objectives[0])
    blackboard.state["mission"]["dispatched"][agent_id] = True
    blackboard.set_mission_status("needs_planning")

    return state

# --- NODE 4: NAVIGATOR ---


def navigator_node(state: RobotState):
    agent_id = state["agent_id"]
    blackboard = state["blackboard"]
    llm = state["llm"]
    pathfinder = state["pathfinder"]
    executor = state["executor"]

    snapshot = blackboard.snapshot()
    current_objective = snapshot.get("mission", {}).get(
        "current_objectives", {}).get(agent_id)

    if not current_objective:
        blackboard.set_mission_status("idle")
        return state

    # Compute reachable targets using A*
    robot_pos = snapshot.get("robots", {}).get(agent_id, {}).get("position")
    reachable_targets = []
    if robot_pos:
        objects = snapshot.get("world_state", {}).get("objects", [])
        walls = [o["position"] for o in objects if o["type"] == "wall"]
        targets = [o for o in objects if o["type"] == "target"]
        for t in targets:
            if pathfinder.find_path(robot_pos, t["position"], walls):
                reachable_targets.append(t["id"])

    prompt = f"""You are the Navigator Agent.
    CURRENT OBJECTIVE: "{current_objective}"
    REACHABLE TARGETS: {reachable_targets}
    Create a tactical plan using available skills."""

    structured_llm = llm.with_structured_output(TacticalPlan)
    try:
        response = structured_llm.invoke(prompt)
        plan_dict = response.dict()
    except Exception as e:
        print(f"LLM failed: {e}")
        plan_dict = {"confidence": 0.1, "plan": [{"skill": "WanderSkill", "parameters": {
            "duration_seconds": 5}, "reason": "Fallback"}]}

    blackboard.set_active_plan(agent_id, plan_dict.get("plan", []))
    executor.load_plan(plan_dict)
    blackboard.set_mission_status("executing")

    return state

# --- NODE 5: EXECUTOR ---


def executor_node(state: RobotState):
    agent_id = state["agent_id"]
    blackboard = state["blackboard"]
    executor = state["executor"]
    agent_type = state["agent_type"]

    status = executor.update()

    if status == "DONE":
        if agent_type == "drone":
            blackboard.set_mission_status("idle")
        else:
            objectives = blackboard.state["mission"]["objectives"].get(
                agent_id, [])
            if objectives:
                objectives.pop(0)

            if objectives:
                blackboard.set_current_objective(agent_id, objectives[0])
                blackboard.set_mission_status("needs_planning")
            else:
                blackboard.set_mission_status("idle")
                blackboard.set_current_objective(agent_id, None)

    elif status == "FAILED":
        current_obj = blackboard.state["mission"]["current_objectives"].get(
            agent_id)
        blackboard.remember_event(
            agent_id, f"Objective '{current_obj}' failed.")
        blackboard.set_mission_status("needs_objectives")

    return state
