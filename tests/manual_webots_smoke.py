"""Optional real-Webots integration smoke test; no cloud model or API key."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))
import app as server
from graph.workflow import build_engine
from test_swarm_graph import ScriptedModel
from world_builder import generate_wbt


def main():
    model = ScriptedModel()
    server.invoke_engine = build_engine(model).invoke
    http = make_server("127.0.0.1", 5000, server.app, threaded=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="autosim-smoke-") as directory:
            project = Path(directory)
            controllers = project / "controllers/autosim_agent"
            shutil.copytree(ROOT / "backend/controllers/autosim_agent", controllers,
                            ignore=shutil.ignore_patterns("__pycache__"))
            (controllers / "runtime.ini").write_text(
                "[python]\nCOMMAND = " + sys.executable.replace("\\", "/") + "\n")
            map_data, run = server.coordinator.start("Visit all targets", {
                "epucks": [{"id": "epuck_1", "x": 0, "z": -4},
                           {"id": "epuck_2", "x": 0, "z": 4}],
                "targets": [{"x": 4, "z": -4}, {"x": -4, "z": 4}, {"x": 4, "z": 0}],
                "drone": {"id": "drone_1", "x": 0, "z": 7},
            })
            world = Path(generate_wbt(map_data, str(project / "worlds/smoke.wbt"), run))
            # Use installed PROTO assets so this test doesn't need asset downloads.
            world.write_text(world.read_text().replace(
                "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/", "webots://"))
            log_path = project / "webots.log"
            with log_path.open("w") as output:
                process = subprocess.Popen([
                    os.getenv("WEBOTS_EXECUTABLE", "webots"), "--batch", "--minimize",
                    "--no-rendering", "--mode=fast", "--stdout", "--stderr", "--port=1235", str(world)
                ], stdout=output, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 50
                while time.monotonic() < deadline and process.poll() is None:
                    with server.state_lock:
                        status = server.coordinator.state["mission"]["status"]
                    if status in ("complete", "failed"):
                        break
                    time.sleep(.1)
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            print("Mission state:", json.dumps(server.coordinator.state, indent=2))
            print("Webots output:", log_path.read_text(errors="replace")[-16000:])
            assert server.coordinator.state["mission"]["status"] == "complete", "Mission did not complete"
            print("PASS: real Webots controllers completed the centrally planned mission")
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        http.shutdown()


if __name__ == "__main__":
    main()
