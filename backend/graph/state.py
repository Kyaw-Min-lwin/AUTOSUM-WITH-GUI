"""
state.py  ─  AutoSim LangGraph State Schema
============================================
Drop-in replacement for blackboard.py.
"""

from __future__ import annotations
from typing import Annotated, Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 ─ TYPE ALIASES (Updated to match Webots executor.py)
# ══════════════════════════════════════════════════════════════════════════════

MissionStatus = Literal[
    "idle",
    "perceiving",
    "needs_planning",
    "needs_objectives",
    "executing",
    "complete",
    "failed",
]

AgentStatus = Literal["idle", "active", "failed", "complete"]

ExecutionPhase = Literal[
    "IDLE", "RUNNING", "DONE", "FAILED"
]  # Matched to Webots status

AgentType = Literal["ground", "aerial"]

SkillStatus = Literal["queued", "RUNNING", "DONE", "FAILED"]  # Matched to Webots status

DangerSeverity = Literal["low", "medium", "high"]


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 ─ DOMAIN MODELS (Pydantic)
# ══════════════════════════════════════════════════════════════════════════════


class Position(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.z == other.z


class Skill(BaseModel):
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    status: SkillStatus = "queued"


class Objective(BaseModel):
    objective_id: str
    description: str
    target_position: Optional[Position] = None
    priority: int = Field(default=1, ge=1, le=10)
    completed: bool = False


class RobotState(BaseModel):
    agent_id: str
    agent_type: AgentType = "ground"
    position: Optional[Position] = None
    heading: Optional[float] = None
    status: AgentStatus = "idle"


class AgentExecutionState(BaseModel):
    agent_id: str
    execution_state: ExecutionPhase = "IDLE"
    active_plan: List[str] = Field(default_factory=list)
    skill_queue: List[Skill] = Field(default_factory=list)
    current_skill: Optional[str] = None
    last_completed_skill: Optional[str] = None


class IdentifiedObject(BaseModel):
    object_id: str
    label: str
    position: Optional[Position] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: float = 0.0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IdentifiedObject):
            return NotImplemented
        return self.object_id == other.object_id


class DynamicObstacle(BaseModel):
    obstacle_id: str
    position: Position
    velocity: Optional[Position] = None
    timestamp: float = 0.0


class DangerZone(BaseModel):
    zone_id: str
    center: Position
    radius: float
    severity: DangerSeverity = "medium"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DangerZone):
            return NotImplemented
        return self.zone_id == other.zone_id


class VisitedLocation(BaseModel):
    agent_id: str
    position: Position
    timestamp: float


class FailedPath(BaseModel):
    agent_id: str
    path_data: Any
    reason: Optional[str] = None
    timestamp: float = 0.0


class EventLog(BaseModel):
    agent_id: str
    event: str
    timestamp: float


class MissionRecord(BaseModel):
    mission: str
    outcome: Optional[str] = None
    timestamp: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 ─ REDUCERS
# ══════════════════════════════════════════════════════════════════════════════


def _last_write_wins(_: Any, new: Any) -> Any:
    return new


def _append_unique(existing: List[Any], incoming: List[Any]) -> List[Any]:
    result = list(existing)
    for item in incoming:
        if item not in result:
            result.append(item)
    return result


def _merge_per_agent_scalar(
    existing: Dict[str, Any], patch: Dict[str, Any]
) -> Dict[str, Any]:
    return {**existing, **patch}


def _merge_per_agent_lists(
    existing: Dict[str, List[Any]], patch: Dict[str, List[Any]]
) -> Dict[str, List[Any]]:
    merged = {k: list(v) for k, v in existing.items()}
    for agent_id, items in patch.items():
        merged.setdefault(agent_id, []).extend(items)
    return merged


def _merge_robot_states(
    existing: Dict[str, RobotState], patch: Dict[str, RobotState]
) -> Dict[str, RobotState]:
    merged = dict(existing)
    for agent_id, update in patch.items():
        if agent_id in merged:
            non_null = {k: v for k, v in update.model_dump().items() if v is not None}
            merged[agent_id] = merged[agent_id].model_copy(update=non_null)
        else:
            merged[agent_id] = update
    return merged


def _merge_execution_states(
    existing: Dict[str, AgentExecutionState], patch: Dict[str, AgentExecutionState]
) -> Dict[str, AgentExecutionState]:
    merged = dict(existing)
    for agent_id, update in patch.items():
        if agent_id in merged:
            non_null = {k: v for k, v in update.model_dump().items() if v is not None}
            merged[agent_id] = merged[agent_id].model_copy(update=non_null)
        else:
            merged[agent_id] = update
    return merged


def _merge_mission(existing: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(existing)
    for key, value in patch.items():
        if key in ("objectives", "current_objectives", "dispatched"):
            result[key] = {**result.get(key, {}), **value}
        elif key == "mission_history":
            result[key] = result.get(key, []) + (value or [])
        else:
            result[key] = value
    return result


def _merge_semantic(existing: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(existing)
    dedup_keys = (
        "identified_objects",
        "danger_zones",
        "reachable_targets",
        "discovered_targets",
    )
    for key, value in patch.items():
        if key == "dynamic_obstacles":
            result[key] = result.get(key, []) + (value or [])
        elif key in dedup_keys:
            existing_items = result.get(key, [])
            new_items = [v for v in (value or []) if v not in existing_items]
            result[key] = existing_items + new_items
        else:
            result[key] = value
    return result


def _merge_memory(existing: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(existing)
    for key, value in patch.items():
        if key in ("visited_locations", "failed_paths", "mission_history"):
            result[key] = result.get(key, []) + (value or [])
        elif key == "event_logs":
            existing_logs: Dict[str, List] = {
                k: list(v) for k, v in result.get("event_logs", {}).items()
            }
            for agent_id, logs in (value or {}).items():
                existing_logs.setdefault(agent_id, []).extend(logs)
            result["event_logs"] = existing_logs
        else:
            result[key] = value
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 ─ SECTION STATES (TypedDicts)
# ══════════════════════════════════════════════════════════════════════════════


class MissionState(TypedDict, total=False):
    user_goal: Optional[str]
    status: MissionStatus
    objectives: Dict[str, List[str]]  # Updated to match our string arrays
    current_objectives: Dict[str, Optional[str]]
    dispatched: Dict[str, bool]
    mission_history: List[MissionRecord]


class SemanticState(TypedDict, total=False):
    identified_objects: List[IdentifiedObject]
    dynamic_obstacles: List[DynamicObstacle]
    danger_zones: List[DangerZone]
    reachable_targets: List[Any]
    discovered_targets: List[Any]
    recon_complete: bool  # Added to support our drone trigger


class MemoryState(TypedDict, total=False):
    visited_locations: List[VisitedLocation]
    failed_paths: List[FailedPath]
    event_logs: Dict[str, List[EventLog]]
    mission_history: List[MissionRecord]


class RuntimeState(TypedDict, total=False):
    tick: int
    last_update: float


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 ─ ROOT SWARM STATE
# ══════════════════════════════════════════════════════════════════════════════


class SwarmState(TypedDict, total=False):
    # ── Orchestrator Injection ────────────────────────────────────────────────
    # Required for the `Send` API to map isolated sub-graphs to specific robots
    current_agent_id: Annotated[Optional[str], _last_write_wins]

    mission: Annotated[MissionState, _merge_mission]
    semantic: Annotated[SemanticState, _merge_semantic]
    robots: Annotated[Dict[str, RobotState], _merge_robot_states]
    execution: Annotated[Dict[str, AgentExecutionState], _merge_execution_states]
    memory: Annotated[MemoryState, _merge_memory]
    runtime: Annotated[RuntimeState, lambda e, p: {**e, **p}]
    world_state: Dict[str, Any]
    messages: Annotated[List[BaseMessage], add_messages]


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 ─ FACTORIES & HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def create_initial_state() -> SwarmState:
    return SwarmState(
        current_agent_id=None,
        mission=MissionState(
            user_goal=None,
            status="idle",
            objectives={},
            current_objectives={},
            dispatched={},
            mission_history=[],
        ),
        semantic=SemanticState(
            identified_objects=[],
            dynamic_obstacles=[],
            danger_zones=[],
            reachable_targets=[],
            discovered_targets=[],
            recon_complete=False,
        ),
        robots={},
        execution={},
        memory=MemoryState(
            visited_locations=[],
            failed_paths=[],
            event_logs={},
            mission_history=[],
        ),
        runtime=RuntimeState(tick=0, last_update=0.0),
        world_state={},
        messages=[],
    )


def register_agent_patch(agent_id: str, agent_type: AgentType = "ground") -> SwarmState:
    return SwarmState(
        mission=MissionState(
            objectives={agent_id: []},
            current_objectives={agent_id: None},
            dispatched={agent_id: False},
        ),
        robots={
            agent_id: RobotState(
                agent_id=agent_id, agent_type=agent_type, status="idle"
            ),
        },
        execution={
            agent_id: AgentExecutionState(agent_id=agent_id),
        },
        memory=MemoryState(
            visited_locations=[],
            failed_paths=[],
            event_logs={agent_id: []},
        ),
    )
