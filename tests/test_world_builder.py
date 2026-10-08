import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from world_builder import generate_wbt


class WorldBuilderTests(unittest.TestCase):
    def test_generated_robots_use_central_controller_and_run_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = generate_wbt({"epucks": [{"id": "epuck_1", "x": 2, "z": -3}],
                                 "drone": {"id": "drone_1", "x": 0, "z": 0}},
                                str(Path(directory) / "mission.wbt"), "run-123")
            world = Path(path).read_text()
        self.assertEqual(world.count('controller "autosim_agent"'), 2)
        self.assertIn('controllerArgs [ "epuck_1" "run-123" ]', world)
        self.assertIn('controllerArgs [ "drone_1" "run-123" ]', world)
        self.assertTrue((BACKEND / "controllers/autosim_agent/autosim_agent.py").is_file())
        self.assertNotIn('controller "autosim_supervisor"', world)
