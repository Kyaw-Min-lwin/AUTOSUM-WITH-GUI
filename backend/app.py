"""Local command server and owner of the swarm's shared mission state."""
from copy import deepcopy
import logging
import os
import subprocess
import threading
import time

from flask import Flask
from flask_socketio import SocketIO
import requests

from mission import MissionCoordinator
from world_builder import generate_wbt

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

coordinator = MissionCoordinator()
state_lock = threading.RLock()
launch_lock = threading.Lock()
webots_process = None
is_thinking = False
brain_pending = False


def invoke_engine(snapshot):
    # Lazy import keeps startup and deterministic tests independent of API credentials.
    from graph.workflow import swarm_engine
    return swarm_engine.invoke(snapshot)


def publish_state():
    with state_lock:
        snapshot = deepcopy(coordinator.state)
    socketio.emit("glass_brain_update", snapshot)
    socketio.emit("mission_status", snapshot["mission"])


def log(message, agent="Director"):
    socketio.emit("agent_log", {"agent": agent, "message": message})


def trigger_cognitive_engine():
    global is_thinking, brain_pending
    with state_lock:
        if not coordinator.needs_planning():
            return
        brain_pending = True
        if is_thinking:
            return
        is_thinking = True  # Reserve before scheduling, under the same lock.
    socketio.start_background_task(run_cognitive_engine)


def run_cognitive_engine():
    global is_thinking, brain_pending
    while True:
        with state_lock:
            if not brain_pending or not coordinator.needs_planning():
                is_thinking = False
                brain_pending = False
                return
            brain_pending = False
            snapshot = coordinator.snapshot()
            mission_id = snapshot["mission"]["id"]
        try:
            result = invoke_engine(snapshot)
            with state_lock:
                payloads = coordinator.apply(mission_id, result)
                # Dispatch while holding the lock so a new mission cannot interleave.
                for payload in payloads:
                    socketio.emit("execute_plan", payload)
                    log(f"Plan dispatched to {payload['agent_id']}")
        except Exception as exc:
            with state_lock:
                coordinator.fail(mission_id, exc)
            log(f"Planning failed: {exc}", "System")
        publish_state()


@app.route("/")
def index():
    return "AutoSim Flask Backend is running."


def wait_for_webots(url, process, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if requests.get(url, timeout=1).status_code == 200:
                return True
        except requests.RequestException:
            pass
        socketio.sleep(.25)
    return False


def simulated_agent_workflow(goal, map_data, mission_id):
    global webots_process
    try:
        with launch_lock:
            with state_lock:
                if mission_id != coordinator.state["mission"]["id"]:
                    return
            if webots_process is not None and webots_process.poll() is None:
                webots_process.terminate()
                try:
                    webots_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    webots_process.kill()
                    webots_process.wait(timeout=5)
            log(f'Mission objective acknowledged: "{goal}"')
            world_path = generate_wbt(map_data, mission_id=mission_id)
            # Do not leave unread stdout/stderr pipes that can block the simulator.
            webots_process = subprocess.Popen([
                os.getenv("WEBOTS_EXECUTABLE", "webots"), "--mode=realtime", "--batch",
                "--minimize", "--stream", world_path,
            ])
            url = "http://127.0.0.1:1234/index.html?url=ws://127.0.0.1:1234"
            if not wait_for_webots("http://127.0.0.1:1234/index.html", webots_process):
                raise RuntimeError("Webots did not start its simulation stream")
            with state_lock:
                if mission_id != coordinator.state["mission"]["id"]:
                    return
                socketio.emit("simulation_ready", {"url": url, "mission_id": mission_id})
    except Exception as exc:
        with state_lock:
            coordinator.fail(mission_id, exc)
        log(f"Simulation could not start: {exc}", "System")
        publish_state()


@socketio.on("submit_goal")
def handle_goal(data):
    try:
        with state_lock:
            map_data, mission_id = coordinator.start(data.get("goal"), data.get("map", {}))
            goal = coordinator.state["mission"]["user_goal"]
    except (ValueError, AttributeError, TypeError) as exc:
        log(str(exc), "System")
        return {"ok": False, "error": str(exc)}
    publish_state()
    socketio.start_background_task(simulated_agent_workflow, goal, map_data, mission_id)
    return {"ok": True, "mission_id": mission_id}


@socketio.on("agent_log")
def relay_agent_log(data):
    socketio.emit("agent_log", data)


@socketio.on("telemetry_update")
def handle_telemetry(data):
    with state_lock:
        accepted = coordinator.telemetry(data)
    if accepted:
        trigger_cognitive_engine()


@socketio.on("skill_status")
def handle_skill_status(data):
    with state_lock:
        accepted = coordinator.status(data)
    if accepted:
        publish_state()
        trigger_cognitive_engine()


if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)
