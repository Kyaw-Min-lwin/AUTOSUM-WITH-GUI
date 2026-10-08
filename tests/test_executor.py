from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

CLIENT = Path(__file__).resolve().parents[1] / "backend/controllers/autosim_agent"
sys.path.insert(0, str(CLIENT))
from executor import PlanExecutor


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.robot = Mock()
        self.robot.getBasicTimeStep.return_value = 32
        self.robot.getFromDef.return_value = None
        self.socket = Mock()
        self.executor = PlanExecutor("epuck_1", self.robot, self.socket, {
            "left_motor": Mock(), "right_motor": Mock(), "proximity_sensors": []})

    def test_missing_target_fails_cleanly_without_duplicate_status_event(self):
        self.executor.load_plan({"plan": [{"skill": "GoToTargetSkill",
                                           "parameters": {"target_id": "MISSING"}}]})
        self.assertEqual(self.executor.update(), "FAILED")
        self.assertIsNone(self.executor.current_skill)
        self.assertFalse(any(call.args[0] == "skill_status" for call in self.socket.emit.call_args_list))

    def test_unknown_skill_fails_cleanly(self):
        self.executor.load_plan({"plan": [{"skill": "InventedSkill"}]})
        self.assertEqual(self.executor.update(), "FAILED")
