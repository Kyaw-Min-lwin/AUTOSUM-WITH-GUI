from flask import Flask
from flask_socketio import SocketIO, emit
import logging
import subprocess
import os, sys, json, threading
from world_builder import generate_wbt
import time
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "graph"))
from state import create_initial_state, register_agent_patch
from workflow import swarm_engine

# Mute the default Flask logging so our console stays clean
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)


app = Flask(__name__)
# Allow CORS so our Electron frontend can talk to this local server
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Keep track of the webots process so we can kill it later
webots_process = None
master_state = create_initial_state()
state_lock = threading.Lock()
is_thinking = False


def trigger_cognitive_engine():
    """Runs the LangGraph workflow in a background thread so physics never freeze."""
    global master_state, is_thinking

    if is_thinking:
        return  # The swarm is already strategizing, don't interrupt it.

    def run_graph():
        global master_state, is_thinking
        with app.app_context():
            is_thinking = True
            try:
                print("\n[Flask Brain] Waking up Swarm Cognitive Engine...")
                updated_state = swarm_engine.invoke(master_state)

                # UPDATE MASTER MEMORY
                with state_lock:
                    master_state = updated_state

                # 3. EXTRACT COMMANDS AND SEND TO WEBOTS
                messages = master_state.get("messages", [])
                for msg in reversed(messages):
                    content = getattr(msg, "content", "")
                    if isinstance(content, str) and "ACTION_LOCKED:" in content:
                        try:
                            # Extract the JSON payload from the message
                            json_str = content.split("ACTION_LOCKED:")[1].strip()
                            payload = json.loads(json_str)

                            # Assuming the payload has an agent_id, send it to Webots!
                            agent_id = payload.get("agent_id")
                            if agent_id:
                                print(
                                    f"[Flask Brain] Dispatching physical plan to {agent_id.upper()}"
                                )
                                socketio.emit("execute_plan", payload)
                        except Exception as e:
                            print(f"[Flask Brain] Failed to parse action payload: {e}")

            finally:
                is_thinking = False
                socketio.emit("glass_brain_update", master_state)

    # Spawn the background task
    socketio.start_background_task(run_graph)


@app.route("/")
def index():
    return "AutoSim Flask Backend is running."


def wait_for_webots(url, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url)
            if r.status_code == 200:
                return True
        except:
            pass
        time.sleep(0.5)
    return False


def simulated_agent_workflow(goal, map_data):
    print(map_data)
    """
    Executes the multi-agent orchestration and launches Webots.
    """
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

        socketio.sleep(5.5)  # Give Webots a second to spin up the web server

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
            {"url": "http://127.0.0.1:1234/index.html?url=ws://127.0.0.1:1234"},
        )
        # url = "http://127.0.0.1:1234/index.html?url=ws://127.0.0.1:1234"
        # if wait_for_webots(url):
        #     socketio.emit(
        #         "simulation_ready",
        #         {"url": "http://127.0.0.1:1234/index.html?url=ws://127.0.0.1:1234"},
        #     )
        # else:
        #     socketio.emit(
        #         "agent_log",
        #         {"agent": "System", "message": "ERROR: Webots stream failed to start."},
        #     )

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
    global master_state
    print(f"The user submitted {data}")
    user_goal = data.get("goal", "")
    map_data = data.get("map", {})

    # Offload the entire workflow to a non-blocking background thread
    socketio.start_background_task(simulated_agent_workflow, user_goal, map_data)
    with state_lock:
        master_state["mission"]["user_goal"] = user_goal
        # Reset dispatch flags so the Strategist knows it needs to re-plan
        for agent_id in master_state["mission"]["dispatched"]:
            master_state["mission"]["dispatched"][agent_id] = False

    # The Strategist will wait for the Drone to hit 2.8m.
    # If the drone already did the recon, it will plan immediately!
    trigger_cognitive_engine()


@socketio.on("agent_log")
def relay_agent_log(data):
    print(f"[RELAY] {data}")
    # Rebroadcast to all connected frontend clients
    socketio.emit("agent_log", data)

swarm_telemetry = {}


@socketio.on("telemetry_update")
def handle_telemetry(data):
    """Catches 32ms telemetry streams from Webots dumb-clients."""
    global master_state

    agent_id = data.get("agent_id")
    agent_type = data.get("type")
    position = data.get("position", [0, 0, 0])

    if not agent_id:
        return

    with state_lock:
        # 1. Register agent if it doesn't exist yet
        if agent_id not in master_state["robots"]:
            patch = register_agent_patch(agent_id, agent_type)
            master_state["robots"].update(patch["robots"])
            master_state["mission"]["objectives"].update(patch["mission"]["objectives"])
            master_state["mission"]["dispatched"].update(patch["mission"]["dispatched"])
            master_state["execution"].update(patch["execution"])

        # 2. Update real-time position in memory without waking the LLM
        master_state["robots"][agent_id]["position"] = {
            "x": position[0],
            "y": position[1],
            "z": position[2],
        }

        # 3. THE ORACLE (Altitude Trigger)
        recon_done = master_state["semantic"].get("recon_complete", False)

        if agent_type == "drone" and not recon_done:
            altitude = position[2]  # Z-axis

            if altitude >= 2.8:
                print("\n[Oracle] AERIAL SCAN COMPLETE. TRIGGERRING SWARM DEPLOYMENT.")

                # Extract targets from the world_state payload sent by the drone
                world_objects = data.get("world_state", {}).get("objects", [])
                targets = [obj for obj in world_objects if obj.get("type") == "target"]

                # Update memory
                master_state["semantic"]["discovered_targets"] = targets
                master_state["semantic"]["recon_complete"] = True

                # WAKE THE BRAIN!
                trigger_cognitive_engine()


@socketio.on("skill_status")
def handle_skill_status(data):
    """Catches DONE/FAILED alerts when a robot finishes a physical task."""
    agent_id = data.get("agent_id")
    status = data.get("status")
    print(f"[Flask Brain] Alert: {agent_id} reported skill execution is {status}.")

    # If a robot finishes moving, it needs its next command. Wake the brain!
    trigger_cognitive_engine()


if __name__ == "__main__":
    print("=" * 50)
    print("AutoSim AI Backend Booting Up on Port 5000...")
    print("=" * 50)
    socketio.run(
        app, port=5000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True
    )
