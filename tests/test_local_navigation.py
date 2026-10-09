"""Regression coverage for navigation improvements imported from the local project."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/controllers/autosim_agent"))
from skills import GoToTargetSkill, PatrolSkill
from executor import PlanExecutor
from graph.actions import validate_step
from test_swarm_graph import ready_mission


class LocalNavigationTests(unittest.TestCase):
    def setUp(self):
        self.robot = Mock()
        self.robot.getBasicTimeStep.return_value = 32
        self.robot.getSelf.return_value.getPosition.return_value = [0, 0, 0]
        self.robot.getSelf.return_value.getOrientation.return_value = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        self.robot.getRoot.return_value.getField.return_value.getCount.return_value = 0
        self.targets = {}
        for i in range(2):
            node = Mock()
            node.getPosition.return_value = [.4, i * .4, 0]
            self.targets[f"TARGET_{i}"] = node
        self.robot.getFromDef.side_effect = self.targets.get
        self.left, self.right = Mock(), Mock()
        self.hardware = {"left_motor": self.left, "right_motor": self.right, "proximity_sensors": []}

    def goto(self, target):
        return GoToTargetSkill("epuck_1", self.robot, None, self.left, self.right, target)

    def test_target_resolves_when_skill_starts_and_normalizes_case(self):
        skill = self.goto("target_0")
        self.robot.getFromDef.assert_not_called()
        skill.start()
        self.robot.getFromDef.assert_called_once_with("TARGET_0")
        self.assertIs(skill.target_node, self.targets["TARGET_0"])
        self.assertTrue(skill.path)

    def test_target_removed_before_activation_fails_and_stops(self):
        skill = self.goto("TARGET_0")
        del self.targets["TARGET_0"]
        skill.start()
        self.assertTrue(skill.failed)
        self.assertTrue(skill.is_complete())
        self.left.setVelocity.assert_called_with(0.0)
        self.right.setVelocity.assert_called_with(0.0)

    def patrol(self, ids):
        return PatrolSkill("epuck_1", self.robot, None, self.left, self.right, ids, GoToTargetSkill)

    def test_patrol_resolves_each_waypoint_when_it_is_activated(self):
        patrol = self.patrol(["TARGET_0", "TARGET_1"])
        patrol.start()
        self.robot.getFromDef.assert_called_once_with("TARGET_0")
        replacement = Mock()
        replacement.getPosition.return_value = [.6, .4, 0]
        self.targets["TARGET_1"] = replacement
        patrol.active_navigation_skill.arrived = True
        patrol.update()
        self.assertEqual(patrol.current_waypoint_index, 1)
        self.assertIs(patrol.active_navigation_skill.target_node, replacement)
        self.assertFalse(patrol.is_complete())

    def test_missing_patrol_waypoint_is_not_silently_skipped(self):
        executor = PlanExecutor("epuck_1", self.robot, None, self.hardware)
        executor.load_plan({"plan": [{"skill": "PatrolSkill",
                                     "parameters": {"waypoints": ["MISSING", "TARGET_0"]}}]})
        self.assertEqual(executor.update(), "FAILED")
        self.assertIsNone(executor.current_skill)

    def test_patrol_propagates_navigation_failure_and_does_not_advance(self):
        patrol = self.patrol(["TARGET_0", "TARGET_1"])
        patrol.start()
        patrol.active_navigation_skill.failed = True
        patrol.update()
        self.assertTrue(patrol.failed)
        self.assertTrue(patrol.is_complete())
        self.assertEqual(patrol.current_waypoint_index, 0)

    def test_both_patrol_parameter_names_produce_the_same_validated_plan(self):
        coordinator, _ = ready_mission()
        state = coordinator.snapshot()
        canonical = validate_step(state, "epuck_1", "PatrolSkill",
                                  {"waypoints": ["TARGET_0", "TARGET_1"]})
        imported = validate_step(state, "epuck_1", "PatrolSkill",
                                 {"waypoint_ids": ["target_0", "target_1"]})
        self.assertEqual(canonical, imported)
        executor = PlanExecutor("epuck_1", self.robot, None, self.hardware)
        executor.load_plan({"plan": [imported]})
        self.assertEqual(executor.update(), "RUNNING")
        self.assertEqual(executor.current_skill.waypoint_ids, ["TARGET_0", "TARGET_1"])

    def test_ambiguous_patrol_parameters_are_rejected(self):
        coordinator, _ = ready_mission()
        with self.assertRaises(ValueError):
            validate_step(coordinator.snapshot(), "epuck_1", "PatrolSkill",
                          {"waypoints": ["TARGET_0"], "waypoint_ids": ["TARGET_1"]})
