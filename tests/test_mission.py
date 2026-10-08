from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from mission import MissionCoordinator


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = MissionCoordinator()
        self.map = {"epucks": [{"id": "epuck_1"}, {"id": "epuck_2"}],
                    "targets": [{"x": 2}, {"x": -2}], "drone": {"id": "drone_1"}}
        _, self.run = self.coordinator.start("Visit both targets", self.map)

    def telemetry(self, rid, z=0, run=None):
        return self.coordinator.telemetry({"mission_id": run or self.run,
            "agent_id": rid, "position": [0, 0, z]})

    def ready(self):
        self.telemetry("epuck_1")
        self.telemetry("epuck_2")
        self.telemetry("drone_1", .8)

    def test_goal_and_complete_roster_are_shared_before_any_robot_connects(self):
        state = self.coordinator.state
        self.assertEqual(state["mission"]["user_goal"], "Visit both targets")
        self.assertEqual(set(state["robots"]), {"epuck_1", "epuck_2", "drone_1"})
        json.dumps(state)

    def test_waits_for_entire_swarm_and_matching_drone_altitude(self):
        self.telemetry("epuck_1")
        self.telemetry("drone_1", .7)
        self.assertFalse(self.coordinator.needs_planning())
        self.telemetry("drone_1", .8)
        self.assertFalse(self.coordinator.needs_planning())
        self.telemetry("epuck_2")
        self.assertTrue(self.coordinator.needs_planning())

    def result(self):
        return {"mission": {"objectives": {"epuck_1": ["TARGET_0", "TARGET_1"], "epuck_2": []},
                            "dispatched": {"epuck_1": True, "epuck_2": True}},
                "plans": {"epuck_1": [{"skill": "GoToTargetSkill", "parameters": {"target_id": "TARGET_0"}}]}}

    def test_completion_advances_once_and_preserves_latest_telemetry(self):
        self.ready()
        self.coordinator.telemetry({"mission_id": self.run, "agent_id": "epuck_1", "position": [1, 2, 0]})
        plan = self.coordinator.apply(self.run, self.result())[0]
        self.assertEqual(self.coordinator.state["robots"]["epuck_1"]["position"], [1, 2, 0])
        self.assertTrue(self.coordinator.status({**plan, "status": "DONE"}))
        self.assertFalse(self.coordinator.status({**plan, "status": "DONE"}))
        self.assertEqual(self.coordinator.state["mission"]["objectives"]["epuck_1"], ["TARGET_1"])
        self.assertTrue(self.coordinator.needs_planning())

    def test_new_mission_rejects_old_telemetry_plans_and_completions(self):
        self.ready()
        plan = self.coordinator.apply(self.run, self.result())[0]
        self.coordinator.start("New goal", {"epucks": [{"id": "epuck_3"}]})
        self.assertFalse(self.telemetry("epuck_1", run=self.run))
        self.assertEqual(self.coordinator.apply(self.run, self.result()), [])
        self.assertFalse(self.coordinator.status({**plan, "status": "DONE"}))
        self.assertEqual(set(self.coordinator.state["robots"]), {"epuck_3"})

    def test_ground_only_map_does_not_wait_for_drone(self):
        _, self.run = self.coordinator.start("Visit target", {"targets": [{"x": 3}]})
        self.telemetry("epuck_1")
        self.assertTrue(self.coordinator.needs_planning())

    def test_failed_action_retries_same_objective_then_stops(self):
        self.ready()
        for attempt in range(3):
            plan = self.coordinator.apply(self.run, self.result())[0]
            self.coordinator.status({**plan, "status": "FAILED"})
        self.assertEqual(self.coordinator.state["mission"]["status"], "failed")
        self.assertFalse(self.coordinator.needs_planning())
        self.assertEqual(len(self.coordinator.state["mission"]["objectives"]["epuck_1"]), 2)

    def test_invalid_map_does_not_destroy_existing_mission(self):
        with self.assertRaises(ValueError):
            self.coordinator.start("Bad run", {"epucks": [{"id": "invalid\""}]})
        self.assertEqual(self.coordinator.state["mission"]["id"], self.run)
