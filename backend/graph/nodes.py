"""LLM reasoning nodes. Physical identity and geometry are supplied by the app."""
from functools import lru_cache
import json
import os

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

from .tools import navigator_tools


@lru_cache(maxsize=1)
def get_llm():
    load_dotenv()
    return ChatGroq(api_key=os.getenv("GROQ_API_KEY"),
                    model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                    temperature=0, timeout=30, max_retries=1)


def strategist_node(state, llm=None):
    mission, robots = state["mission"], state["robots"]
    ground = [rid for rid, robot in robots.items() if robot["type"] == "ground"]
    if not ground or not state["semantic"]["recon_complete"] or not all(r["ready"] for r in robots.values()):
        return {}
    # Inspect every flag value; a populated dictionary alone does not mean dispatched.
    if all(mission["dispatched"].get(rid, False) for rid in ground):
        return {}
    targets = [t["id"] for t in state["semantic"]["discovered_targets"]]
    prompt = f"""You allocate a robot swarm's mission.
Active ground robots: {ground}
Known targets: {targets}
Return a JSON object with EXACTLY one key per ground robot and an array of
high-level objective strings for each. Empty arrays mean no work for that robot.
Divide targets fairly, with no duplicate assignments unless the user explicitly
requests cooperation. For following, choose one leader and give that leader
its own movement objective; followers must identify that leader by its ID.
Each objective must be achievable by ONE GoToTarget, Wander, SpinScan,
FollowLeader or Patrol skill; split sequential finite tasks into separate objectives.
Follow and Patrol are continuous; put them last. Obey the supplied user goal.
"""
    model = (llm or get_llm()).bind(response_format={"type": "json_object"})
    messages = [SystemMessage(content=prompt), HumanMessage(content=mission["user_goal"])]
    for _ in range(3):
        response = model.invoke(messages)
        try:
            allocation = json.loads(response.content)
            if not isinstance(allocation, dict) or set(allocation) != set(ground):
                raise ValueError("Assignments must contain exactly the registered ground robot IDs")
            if any(not isinstance(items, list)
                   or any(not isinstance(item, str) or not item.strip() for item in items)
                   for items in allocation.values()):
                raise ValueError("Each assignment must be an array of nonempty objective strings")
            if not any(allocation.values()):
                raise ValueError("The mission needs at least one actionable objective")
            return {"mission": {"objectives": allocation,
                                "dispatched": {rid: True for rid in ground}}}
        except (ValueError, TypeError) as exc:
            messages.append(HumanMessage(content=f"Invalid allocation: {exc}. Return corrected JSON."))
    raise ValueError("Strategist could not produce valid swarm assignments")


def navigator_node(state, llm=None):
    agent_id, swarm = state["agent_id"], state["swarm"]
    objective = swarm["mission"]["objectives"][agent_id][0]
    prompt = f"""You are the navigator for {agent_id}.
Objective: {objective}
Mission: {swarm['mission']['user_goal']}
Robots: {json.dumps(swarm['robots'])}
World objects: {json.dumps(swarm['world_state']['objects'])}
Previous execution error: {swarm['execution'][agent_id].get('error', 'none')}
Use check_path_feasibility before GoToTarget. Then call dispatch_physical_action
with ONE skill to fulfill this objective. Use only the IDs shown above.
Do not substitute wandering for an unreachable target; report failure instead.
Following and patrolling are continuous. Never dispatch more than one action.
"""
    model = (llm or get_llm()).bind_tools(navigator_tools)
    response = model.invoke([SystemMessage(content=prompt)] + state.get("messages", []))
    return {"messages": [response], "attempts": state.get("attempts", 0) + 1}
