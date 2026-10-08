from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import app as server
from mission import MissionCoordinator
from graph.workflow import build_engine
from test_swarm_graph import ScriptedModel


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        server.coordinator = MissionCoordinator()
        server.is_thinking = False
        server.brain_pending = False
        self.client = server.socketio.test_client(server.app)
        self.tasks = []
        self.scheduler = patch.object(server.socketio, "start_background_task",
                                      side_effect=lambda fn, *a: self.tasks.append((fn, a)))
        self.scheduler.start()
        self.addCleanup(self.scheduler.stop)
        self.addCleanup(self.client.disconnect)
        self.model = ScriptedModel()
        self.engine = build_engine(self.model)
        self.engine_patch = patch.object(server, "invoke_engine", self.engine.invoke)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)

    def submit(self, goal="Visit all targets"):
        response = self.client.emit("submit_goal", {"goal": goal, "map": {
            "epucks": [{"id": "epuck_1"}, {"id": "epuck_2"}],
            "targets": [{"x": 4}, {"x": -4}], "drone": {"id": "drone_1"},
        }}, callback=True)
        self.assertTrue(response["ok"])
        return response["mission_id"]

    def ready(self, run):
        for rid in ("epuck_1", "epuck_2", "drone_1"):
            self.client.emit("telemetry_update", {
                "mission_id": run, "agent_id": rid, "position": [0, 0, .8 if rid == "drone_1" else 0]
            })

    def plans(self):
        return [event["args"][0] for event in self.client.get_received() if event["name"] == "execute_plan"]

    def test_gui_goal_to_graph_to_robot_and_completion(self):
        run = self.submit("Send the swarm to all targets")
        self.ready(run)
        self.assertEqual(sum(fn == server.run_cognitive_engine for fn, _ in self.tasks), 1)
        server.run_cognitive_engine()
        plans = self.plans()
        self.assertEqual(self.model.goal, "Send the swarm to all targets")
        self.assertEqual({p["agent_id"] for p in plans}, {"epuck_1", "epuck_2"})
        self.assertTrue(all(p["mission_id"] == run for p in plans))
        first = next(p for p in plans if p["agent_id"] == "epuck_1")
        self.client.emit("skill_status", {**first, "status": "DONE"})
        self.client.emit("skill_status", {**first, "status": "DONE"})
        server.run_cognitive_engine()
        next_plans = self.plans()
        self.assertEqual(len(next_plans), 1)
        self.assertNotEqual(next_plans[0]["plan_id"], first["plan_id"])
        self.assertEqual(next_plans[0]["plan"][0]["parameters"]["target_id"], "TARGET_1")
        for plan in [next_plans[0], next(p for p in plans if p["agent_id"] == "epuck_2")]:
            self.client.emit("skill_status", {**plan, "status": "DONE"})
        self.assertEqual(server.coordinator.state["mission"]["status"], "complete")

    def test_new_run_during_inference_discards_old_results_and_keeps_new_wakeup(self):
        old_run = self.submit()
        self.ready(old_run)
        calls = []

        def invoke(snapshot):
            calls.append(snapshot["mission"]["id"])
            if len(calls) == 1:
                new_run = self.submit("A new mission")
                self.ready(new_run)
            return self.engine.invoke(snapshot)

        with patch.object(server, "invoke_engine", side_effect=invoke):
            server.run_cognitive_engine()
        plans = self.plans()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(plans), 2)
        self.assertTrue(all(p["mission_id"] != old_run for p in plans))
        self.assertFalse(server.is_thinking)
