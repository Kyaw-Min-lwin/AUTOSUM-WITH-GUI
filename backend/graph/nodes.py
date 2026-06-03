import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
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

def navigator_node(state: dict):
    """
    The Tactical Reasoning Agent. 
    It evaluates the environment, calls tools to check physics, and dispatches actions.
    """
    agent_id = state.get("current_agent_id", "epuck_1") # Provided by the Orchestrator
    objective = state["mission"]["current_objectives"].get(agent_id, "Wait for orders.")
    
    # 1. Extract local environment data to prevent token bloat
    semantic_data = state.get("semantic_state", {})
    targets = [t["id"] for t in semantic_data.get("discovered_targets", [])]
    
    # 2. The Agentic Prompt
    system_prompt = f"""
    You are the Tactical Navigator for {agent_id}.
    Your current objective is: "{objective}"
    
    ENVIRONMENT:
    Known Targets: {targets}
    
    INSTRUCTIONS:
    1. If you need to move to a target, ALWAYS use 'check_path_feasibility' first.
    2. If the path is blocked, do not dispatch GoToTarget. Dispatch 'WanderSkill' or 'SpinScanSkill' to find a new route.
    3. Once you are certain of your action, call 'dispatch_physical_action'.
    """
    
    # 3. Invoke the LLM with the prompt and its previous thoughts/tool results
    messages = [SystemMessage(content=system_prompt)] + state.get("messages", [])
    response = navigator_llm.invoke(messages)
    
    # 4. Return the LLM's output to be appended to the state
    return {"messages": [response]}


# force it to strictly return JSON
strategist_llm = llm.bind(response_format={"type": "json_object"})

def strategist_node(state: dict):
    """
    The Swarm Orchestrator (CEO Node).
    Reads the global map, divides labor, and assigns objectives to individual robots.
    """
    mission = state.get("mission", {})
    semantic = state.get("semantic_state", {})
    robots = state.get("robots", {})
    
    # 1. GATEKEEPER: Don't plan if recon isn't done or if we already planned!
    if not semantic.get("recon_complete", False):
        return {"messages": ["Strategist: Awaiting aerial intelligence..."]}
        
    if mission.get("dispatched", False):
        return {} # We already built the plan, do nothing!

    # 2. Gather data
    ground_swarm = [rid for rid, data in robots.items() if data.get("type") == "ground"]
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

    # 7. Return the Patch! 
    # This updates the global state, injecting the task lists into the memory.
    return {
        "mission": {
            "objectives": task_distribution,
            "dispatched": True # Lock it so we don't plan again
        },
        "messages": [f"Strategist deployed tactical plan: {task_distribution}"]
    }