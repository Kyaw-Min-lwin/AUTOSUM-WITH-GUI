import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from state import SwarmState
from tools import check_path_feasibility, calculate_spatial_relationship, dispatch_physical_action
import json 

load_dotenv()
# 1. Initialize the LLM (Using Groq for real-time robotics speed)
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="openai/gpt-oss-120b", 
    temperature=0.0 
)

# 2. Bind the physical tools to the LLM
navigator_tools = [check_path_feasibility, calculate_spatial_relationship, dispatch_physical_action]
navigator_llm = llm.bind_tools(navigator_tools)
strategist_llm = llm.bind(response_format={"type": "json_object"})


def navigator_node(state: SwarmState):
    """The Tactical Reasoning Agent."""

    agent_id = state.get("current_agent_id", "epuck_1")

    # state.py nests objectives inside the mission dictionary
    objective_list = state.get("mission", {}).get("objectives", {}).get(agent_id, [])
    objective = objective_list[0] if objective_list else "Wait for orders."

    targets = [
        t.object_id for t in state.get("semantic", {}).get("discovered_targets", [])
    ]

    system_prompt = f"""
    You are the Tactical Navigator for {agent_id}.
    Objective: "{objective}"
    Known Targets: {targets}
    
    1. Use 'check_path_feasibility' to verify paths.
    2. Once certain, call 'dispatch_physical_action'.
    3. You MUST provide your own name ('{agent_id}') as the agent_id parameter in the tool!
    """

    messages = [SystemMessage(content=system_prompt)] + state.get("messages", [])
    response = navigator_llm.invoke(messages)

    return {"messages": [response]}


def strategist_node(state: dict):
    """
    The Swarm Orchestrator (CEO Node).
    Reads the global map, divides labor, and assigns objectives to individual robots.
    """
    mission = state.get("mission", {})
    semantic = state.get("semantic", {})
    robots = state.get("robots", {})

    # 1. GATEKEEPER: Don't plan if recon isn't done or if we already planned!
    if not semantic.get("recon_complete", False):
        return {"messages": ["Strategist: Awaiting aerial intelligence..."]}

    if mission.get("dispatched", False):
        return {} # We already built the plan, do nothing!

    # 2. Gather data
    ground_swarm = [rid for rid, data in robots.items() if data.get("type") == "ground"]

    # Check if we already dispatched for ALL ground units
    all_dispatched = all(
        mission.get("dispatched", {}).get(rid, False) for rid in ground_swarm
    )
    if all_dispatched and ground_swarm:
        return {}
    targets = [t["id"] for t in semantic.get("discovered_targets", [])]
    user_goal = mission.get("user_goal", "Explore the area")

    # 3. Dynamic JSON Template (Scales to any number of robots)
    dynamic_json_example = {robot_id: [f"Tactical objective for {robot_id}"] for robot_id in ground_swarm}

    # 4. The Orchestrator Prompt
    system_prompt = f"""
    You are the Swarm Strategist for a multi-agent robotics system.
    USER COMMAND: "{user_goal}"
    
    ENVIRONMENT:
    Discovered Targets: {targets}
    ACTIVE GROUND UNITS: {ground_swarm}
    
    YOUR DIRECTIVE:
    Divide the targets fairly among the ACTIVE GROUND UNITS to fulfill the USER COMMAND.
    Do NOT assign the same target to multiple robots unless explicitly requested.
    
    You MUST output valid JSON strictly following this format:
    {json.dumps(dynamic_json_example, indent=4)}
    """

    # 5. Invoke the LLM
    response = strategist_llm.invoke([SystemMessage(content=system_prompt)])

    # 6. Parse and apply to the State
    try:
        task_distribution = json.loads(response.content)
    except Exception as e:
        # Fallback in case of absolute failure
        print(f"[Strategist] JSON Parse Error: {e}")
        task_distribution = {rid: ["Explore the environment"] for rid in ground_swarm}

    dispatch_flags = {rid: True for rid in ground_swarm}

    # 7. Return the Patch!
    # This updates the global state, injecting the task lists into the memory.
    return {
        "mission": {"objectives": task_distribution, "dispatched": dispatch_flags},
        "messages": [f"Strategist deployed tactical plan: {task_distribution}"],
    }
