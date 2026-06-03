import sys
import socketio
from controller import Supervisor
from world_state import WorldState
from executor import PlanExecutor

supervisor = Supervisor()
TIME_STEP = int(supervisor.getBasicTimeStep())
sio = socketio.Client()

# ==========================================
# MULTI-AGENT IDENTITY ASSIGNMENT
# ==========================================
agent_id = sys.argv[1] if len(sys.argv) > 1 else "epuck_1"
agent_type = "drone" if "drone" in agent_id.lower() else "ground"

try:
    print(f"[{agent_id.upper()}] Attempting to connect to Flask Command Center...")
    sio.connect("http://localhost:5000")
except Exception as e:
    sys.exit(1)


@sio.event
def connect():
    sio.emit(
        "agent_log",
        {"agent": agent_id, "message": "Hardware online. Awaiting commands."},
    )


# ==========================================
# LISTEN FOR COMMANDS FROM FLASK
# ==========================================
@sio.on("execute_plan")
def on_execute_plan(data):
    """Listens for the LangGraph orchestrator sending a validated JSON skill plan."""
    if data.get("agent_id") == agent_id:
        print(f"[{agent_id.upper()}] Received new tactical plan from Swarm Command.")
        executor.load_plan(data)


# 1. Initialize hardware
left_motor = None
right_motor = None
proximity_sensors = []

if agent_type == "ground":
    left_motor = supervisor.getDevice("left wheel motor")
    right_motor = supervisor.getDevice("right wheel motor")

    for i in range(8):
        sensor = supervisor.getDevice(f"ps{i}")
        if sensor:
            sensor.enable(TIME_STEP)
            proximity_sensors.append(sensor)

    if left_motor and right_motor:
        left_motor.setPosition(float("inf"))
        right_motor.setPosition(float("inf"))
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)

hardware_map = {
    "left_motor": left_motor,
    "right_motor": right_motor,
    "proximity_sensors": proximity_sensors,
}

print(f"[{agent_id.upper()}] Booting execution engine...")

# 2. Initialize Core Systems (NO LLMS, NO BLACKBOARD!)
world = WorldState(supervisor, proximity_sensors)
executor = PlanExecutor(agent_id, supervisor, sio, hardware_map)

tick = 0

# ==========================================
# THE DUMB CLIENT LOOP
# ==========================================
while supervisor.step(TIME_STEP) != -1:
    # 1. READ SENSORS
    world.update_objects()
    world.update_runtime()

    robot_node = supervisor.getSelf()
    position = robot_node.getPosition()
    orientation = robot_node.getOrientation()

    # 2. STREAM TELEMETRY TO FLASK
    if tick % 15 == 0:
        telemetry_payload = {
            "agent_id": agent_id,
            "type": agent_type,
            "position": position,
            "heading": orientation,
            "world_state": world.get_state(),
        }
        sio.emit("telemetry_update", telemetry_payload)

    # 3. EXECUTE MOTORS
    status = executor.update()

    # 4. REPORT SKILL COMPLETION
    # If a skill finishes or fails, tell the Flask server so LangGraph can calculate the next move
    if status in ["DONE", "FAILED"]:
        print(f"[{agent_id.upper()}] Skill {status}. Alerting Swarm Command.")
        sio.emit("skill_status", {"agent_id": agent_id, "status": status})

        # Reset executor status to IDLE so we don't spam the server
        executor.status = "IDLE"

    tick += 1
