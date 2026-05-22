from pydantic import BaseModel, Field
from typing import Dict, List, Any

# For the Mission Director


class SwarmAllocation(BaseModel):
    allocations: Dict[str, List[str]] = Field(
        description="Mapping of agent_id to a list of tactical objectives."
    )

# For the Navigator Agent


class TacticalStep(BaseModel):
    skill: str = Field(description="Name of the skill to execute.")
    parameters: Dict[str, Any] = Field(
        description="Parameters required for the skill.")
    reason: str = Field(description="Reasoning for this step.")


class TacticalPlan(BaseModel):
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0")
    plan: List[TacticalStep] = Field(
        description="Sequence of tactical steps to execute.")
