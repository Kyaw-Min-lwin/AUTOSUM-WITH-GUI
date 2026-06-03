from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.constants import Send
from nodes import strategist_node, navigator_node, navigator_tools
from state import SwarmState

# ==========================================
# 1. THE ROUTING FUNCTIONS
# ==========================================
def dispatch_swarm(state: dict):
    """
    The Map-Reduce Router.
    Reads the objectives assigned by the Strategist and spawns a parallel 
    Navigator graph for every single ground robot.
    """
    objectives = state.get("mission", {}).get("objectives", {})
    
    # If the Strategist failed or gave no objectives, end the graph tick.
    if not objectives:
        return END
        
    # Spawn a parallel Navigator for each robot that received a task
    # We use the Send API to pass a focused, local state to each worker
    parallel_workers = []
    for agent_id in objectives.keys():
        worker_state = {
            # We pass the global state but inject the specific agent_id
            **state, 
            "current_agent_id": agent_id
        }
        parallel_workers.append(Send("navigator", worker_state))
        
    return parallel_workers

def check_navigator_finished(state: dict):
    """
    The ReAct Loop Router.
    Checks if the Navigator called a Tool (like A* pathfinding) or 
    dispatched a final physical action.
    """
    last_message = state["messages"][-1]
    
    # If the LLM decided to call a physical tool (e.g., check_path_feasibility)
    if getattr(last_message, "tool_calls", None):
        return "tools"
        
    # If the LLM outputted a final action string (e.g., "ACTION_LOCKED: {...}")
    return END

# ==========================================
# 2. BUILD THE GRAPH
# ==========================================
builder = StateGraph(SwarmState)

# Add the AI Brains (Nodes)
builder.add_node("strategist", strategist_node)
builder.add_node("navigator", navigator_node)

# Add the Tool Belt (Using LangGraph's prebuilt ToolNode to automatically execute our Python functions)
builder.add_node("tools", ToolNode(navigator_tools))

# ==========================================
# 3. WIRE THE EDGES (The Agentic Flow)
# ==========================================
# Step 1: Always start by asking the Strategist to evaluate the global map
builder.add_edge(START, "strategist")

# Step 2: Strategist finishes -> Spawn parallel Navigators for epuck_1, epuck_2, etc.
builder.add_conditional_edges("strategist", dispatch_swarm, ["navigator", END])

# Step 3: Navigator finishes thinking -> Did it call a tool, or is it done?
builder.add_conditional_edges("navigator", check_navigator_finished, ["tools", END])

# Step 4: Tool finishes running the math -> Route back to the Navigator to evaluate the result
builder.add_edge("tools", "navigator")

# ==========================================
# 4. COMPILE THE ENGINE
# ==========================================
# We compile the graph. You can later add memory savers here for time-travel debugging!
swarm_engine = builder.compile()

print("[LangGraph] Sovereign Swarm Cognitive Engine Compiled Successfully.")