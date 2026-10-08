"""JSON-compatible state shared by Flask, LangGraph and Socket.IO.

Use one wire representation throughout: dictionary fields are never sometimes
Pydantic objects and sometimes dictionaries.
"""
from typing import Annotated, Any
from typing_extensions import TypedDict


def merge_agents(existing, patch):
    return {**existing, **patch}


def merge_mission(existing, patch):
    result = dict(existing)
    for key, value in patch.items():
        result[key] = ({**result.get(key, {}), **value}
                       if key in ("objectives", "dispatched") else value)
    return result


class SwarmState(TypedDict, total=False):
    mission: Annotated[dict, merge_mission]
    semantic: dict
    robots: Annotated[dict, merge_agents]
    execution: Annotated[dict, merge_agents]
    world_state: dict
    plans: Annotated[dict, merge_agents]
    planning_errors: Annotated[dict, merge_agents]


def create_initial_state():
    return {
        "mission": {"id": None, "user_goal": "", "status": "idle",
                    "objectives": {}, "dispatched": {}},
        "semantic": {"recon_complete": False, "discovered_targets": []},
        "robots": {}, "execution": {}, "world_state": {"objects": []},
        "plans": {}, "planning_errors": {},
    }


def register_agent_patch(agent_id, agent_type="ground"):
    return {
        "mission": {"objectives": {agent_id: []}, "dispatched": {agent_id: False}},
        "robots": {agent_id: {"type": agent_type, "position": None, "ready": False}},
        "execution": {agent_id: {"status": "IDLE", "plan_id": None, "attempts": 0}},
    }
