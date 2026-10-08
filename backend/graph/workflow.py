"""One strategist and an isolated ReAct subgraph for each ready robot."""
import json
from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Send

from .nodes import strategist_node, navigator_node
from .state import SwarmState
from .tools import navigator_tools


class NavigatorState(TypedDict, total=False):
    swarm: dict
    agent_id: str
    messages: Annotated[list, add_messages]
    attempts: int


def locked_plan(state):
    # Only the latest tool batch can commit a plan. Never replay conversation history.
    actions = []
    for message in reversed(state.get("messages", [])):
        if not isinstance(message, ToolMessage):
            break
        if (message.name == "dispatch_physical_action"
                and isinstance(message.content, str)
                and message.content.startswith("ACTION_LOCKED: ")):
            actions.append(json.loads(message.content.removeprefix("ACTION_LOCKED: ")))
    if len(actions) != 1:
        return None
    payload = actions[0]
    return payload["plan"] if payload["agent_id"] == state["agent_id"] else None


def dispatch_swarm(state):
    if not state["semantic"]["recon_complete"] or not all(r["ready"] for r in state["robots"].values()):
        return END
    workers = [
        Send("navigate_robot", {"swarm": state, "agent_id": rid, "messages": [], "attempts": 0})
        for rid, objectives in state["mission"]["objectives"].items()
        if objectives and state["robots"][rid]["type"] == "ground"
        and state["execution"][rid]["status"] == "IDLE"
    ]
    return workers or END


def build_engine(llm=None):
    worker = StateGraph(NavigatorState)
    worker.add_node("navigator", lambda state: navigator_node(state, llm))
    worker.add_node("tools", ToolNode(navigator_tools, handle_tool_errors=True))
    worker.add_edge(START, "navigator")

    def after_navigator(state):
        calls = getattr(state["messages"][-1], "tool_calls", [])
        # A final dispatch must be alone: don't execute multiple competing plans.
        dispatches = [call for call in calls if call["name"] == "dispatch_physical_action"]
        if dispatches and len(calls) != 1:
            return END
        return "tools" if calls else END

    def after_tools(state):
        if locked_plan(state) is not None or state["attempts"] >= 4:
            return END
        return "navigator"

    worker.add_conditional_edges("navigator", after_navigator, ["tools", END])
    worker.add_conditional_edges("tools", after_tools, ["navigator", END])
    navigation = worker.compile()

    def navigate_robot(state):
        rid = state["agent_id"]
        try:
            result = navigation.invoke(state)
            plan = locked_plan(result)
            if plan is None:
                raise ValueError("Navigator did not commit one valid physical action")
            return {"plans": {rid: plan}}
        except Exception as exc:
            return {"planning_errors": {rid: str(exc)}}

    graph = StateGraph(SwarmState)
    graph.add_node("strategist", lambda state: strategist_node(state, llm))
    graph.add_node("navigate_robot", navigate_robot)
    graph.add_edge(START, "strategist")
    graph.add_conditional_edges("strategist", dispatch_swarm, ["navigate_robot", END])
    graph.add_edge("navigate_robot", END)
    return graph.compile()


swarm_engine = build_engine()
