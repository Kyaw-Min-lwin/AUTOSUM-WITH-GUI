from flask import Flask
from flask_socketio import SocketIO, emit
import logging
import subprocess
import os
from world_builder import generate_wbt
import time
import requests
import json

# Mute the default Flask logging so our console stays clean
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app = Flask(__name__)
# Allow CORS so our Electron frontend can talk to this local server
socketio = SocketIO(app, cors_allowed_origins="*")

# Keep track of the webots process so we can kill it later
webots_process = None
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config_dir = os.path.join(BASE_DIR, "controllers", "autosim_supervisor")
os.makedirs(config_dir, exist_ok=True)
config_path = os.path.join(config_dir, "mission_config.json")


@app.route("/")
def index():
    return "AutoSim Flask Backend is running."


def wait_for_webots_stream(timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get("http://127.0.0.1:1234/index.html")
            if response.status_code == 200:
                return True
        except:
            pass
        time.sleep(0.5)
    return False


def simulated_agent_workflow(goal, map_data):
    print(map_data)
    mission_payload = {"goal": goal, "map": map_data}
    with open(config_path, "w") as f:
        json.dump(mission_payload, f, indent=4)

    global webots_process
    socketio.sleep(0.5)
    socketio.emit(
        "agent_log",
        {"agent": "Director", "message": f'Mission objective acknowledged: "{goal}"'},
    )

    socketio.sleep(1.0)
    socketio.emit(
        "agent_log",
        {
            "agent": "Oracle",
            "message": "Checking kinematic constraints for E-puck ground unit... clear.",
        },
    )

    socketio.sleep(1.0)
    socketio.emit(
        "agent_log",
        {"agent": "Forge", "message": "Compiling Webots .wbt physics environment..."},
    )

    # --- NEW: Generate the World ---
    world_path = generate_wbt(map_data, filepath="worlds/temp_run.wbt")

    socketio.sleep(1.0)
    socketio.emit(
        "agent_log",
        {
            "agent": "Inspector",
            "message": "World compiled successfully. Booting Webots TCP Stream...",
        },
    )

    # ---  Launch Webots ---
    try:
        if webots_process is not None:
            webots_process.terminate()  # Kill old instance if running

        cmd = [
            "webots",
            "--mode=realtime",
            "--batch",
            "--minimize",
            "--stream",
            world_path,
        ]
        webots_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        print(webots_process.stdout.readline())

        if not wait_for_webots_stream():
            socketio.emit(
                "agent_log",
                {
                    "agent": "System",
                    "message": "ERROR: Webots stream failed to initialize.",
                },
            )

            return

        socketio.emit(
            "agent_log",
            {
                "agent": "Director",
                "message": "Stream active. Transferring UI control to Canvas.",
            },
        )
        print("sim ready")
        socketio.emit(
            "simulation_ready",
            {"ready": True},
        )

    except FileNotFoundError:
        socketio.emit(
            "agent_log",
            {
                "agent": "System",
                "message": "ERROR: Webots executable not found in PATH.",
            },
        )


# Listen for the user submitting a goal from the UI
@socketio.on("submit_goal")
def handle_goal(data):
    print(f"The user submitted {data}")
    user_goal = data.get("goal", "")
    map_data = data.get("map", {})

    # Offload the entire workflow to a non-blocking background thread
    socketio.start_background_task(simulated_agent_workflow, user_goal, map_data)


@socketio.on("agent_log")
def relay_agent_log(data):
    print(f"[RELAY] {data}")
    # Rebroadcast to all connected frontend clients
    socketio.emit("agent_log", data)


if __name__ == "__main__":
    print("=" * 50)
    print("AutoSim AI Backend Booting Up on Port 5000...")
    print("=" * 50)
    socketio.run(
        app, port=5000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True
    )
