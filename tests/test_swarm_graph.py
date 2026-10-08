import json
from pathlib import Path
import re
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from langchain_core.messages import AIMessage, ToolMessage
from graph.workflow import build_engine
from graph.actions import validate_step
from mission import MissionCoordinator


class ScriptedModel:
    """Replace only network inference; run the real graph, tools and reducers."""
    def __init__(self, invalid_skill=False):
        self.lock = threading.Lock()
        self.strategist_calls = 0
        self.contexts = []
        self.invalid_skill = invalid_skill

    def bind(self, **kwargs):
        return self

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        prompt = messages[0].content
        if "allocate a robot swarm" in prompt:
            with self.lock:
                self.strategist_calls += 1
                self.goal = messages[1].content
            return AIMessage(content=json.dumps({
                "epuck_1": ["Navigate to TARGET_0", "Navigate to TARGET_1"],
                "epuck_2": ["Navigate to TARGET_1"],
            }))
        rid = re.search(r"navigator for (epuck_\d+)", prompt).group(1)
        target = re.search(r"Objective: Navigate to (TARGET_\d+)", prompt).group(1)
        with self.lock:
            self.contexts.append((rid, messages))
        if not any(isinstance(m, ToolMessage) for m in messages):
            name, args = "check_path_feasibility", {"target_id": target}
        else:
            name = "dispatch_physical_action"
            args = {"skill_name": "InventedSkill" if self.invalid_skill else "GoToTargetSkill",
                    "parameters": {"target_id": target}}
        return AIMessage(content="", tool_calls=[{"name": name, "args": args,
                                                  "id": f"{rid}-{len(messages)}"}])


def ready_mission():
    coordinator = MissionCoordinator()
    _, run = coordinator.start("Visit all targets", {
        "epucks": [{"id": "epuck_1"}, {"id": "epuck_2"}],
        "targets": [{"x": 4, "z": 0}, {"x": -4, "z": 0}],
    })
    for rid in ("epuck_1", "epuck_2"):
        coordinator.telemetry({"mission_id": run, "agent_id": rid, "position": [0, 0, 0]})
    return coordinator, run


class SwarmGraphTests(unittest.TestCase):
    def test_false_dispatch_flags_allocate_once_and_workers_keep_their_identity(self):
        coordinator, run = ready_mission()
        model = ScriptedModel()
        engine = build_engine(model)
        result = engine.invoke(coordinator.snapshot())
        self.assertEqual(model.goal, "Visit all targets")
        self.assertEqual(model.strategist_calls, 1)
        self.assertEqual(result["plans"]["epuck_1"][0]["parameters"]["target_id"], "TARGET_0")
        self.assertEqual(result["plans"]["epuck_2"][0]["parameters"]["target_id"], "TARGET_1")
        for rid, messages in model.contexts:
            for message in messages[1:]:
                for call in getattr(message, "tool_calls", []):
                    self.assertTrue(call["id"].startswith(rid))
        payloads = coordinator.apply(run, result)
        completed = next(p for p in payloads if p["agent_id"] == "epuck_1")
        coordinator.status({**completed, "status": "DONE"})
        result2 = engine.invoke(coordinator.snapshot())
        self.assertEqual(model.strategist_calls, 1)
        self.assertEqual(set(result2["plans"]), {"epuck_1"})
        self.assertEqual(result2["plans"]["epuck_1"][0]["parameters"]["target_id"], "TARGET_1")

    def test_invalid_action_never_reaches_robots_and_retry_loop_is_bounded(self):
        coordinator, run = ready_mission()
        model = ScriptedModel(invalid_skill=True)
        result = build_engine(model).invoke(coordinator.snapshot())
        self.assertEqual(result["plans"], {})
        self.assertEqual(set(result["planning_errors"]), {"epuck_1", "epuck_2"})
        self.assertEqual(coordinator.apply(run, result), [])
        self.assertLessEqual(len(model.contexts), 8)

    def test_no_planning_before_full_roster_is_ready(self):
        coordinator, _ = ready_mission()
        coordinator.state["robots"]["epuck_2"]["ready"] = False
        model = ScriptedModel()
        result = build_engine(model).invoke(coordinator.snapshot())
        self.assertEqual(model.strategist_calls, 0)
        self.assertEqual(result["plans"], {})

    def test_action_validation_checks_identity_targets_and_parameters(self):
        coordinator, _ = ready_mission()
        state = coordinator.snapshot()
        for skill, params in [
            ("GoToTargetSkill", {"target_id": "TARGET_999"}),
            ("FollowLeaderSkill", {"leader_id": "epuck_1"}),
            ("WanderSkill", {"duration_seconds": -1}),
            ("PatrolSkill", {}),
        ]:
            with self.subTest(skill=skill), self.assertRaises(ValueError):
                validate_step(state, "epuck_1", skill, params)
