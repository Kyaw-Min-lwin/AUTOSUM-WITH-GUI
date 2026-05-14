import sys
import socketio
from controller import Supervisor
from world_state import WorldState
from llm_client import GroqClient
from planner import PlannerAgent
from executor import PlanExecutor
from skills import AvoidObstacleSkill

supervisor = Supervisor()
TIME_STEP = int(supervisor.getBasicTimeStep())

sio = socketio.Client()

try:
    print("[E-PUCK] Attempting to connect to Flask Command Center...")
    sio.connect("http://localhost:5000")
except Exception as e:
    print(f"[E-PUCK] CRITICAL ERROR: Could not connect to Flask: {e}")
    sys.exit(1)


@sio.event
def connect():
    sio.emit(
        "agent_log",
        {"agent": "E-Puck", "message": "Hardware online. Telemetry link established."},
    )


@sio.event
def disconnect():
    print("[E-PUCK] Disconnected from Command Center.")


# 1. Initialize motors once before the loop
left_motor = supervisor.getDevice("left wheel motor")
right_motor = supervisor.getDevice("right wheel motor")
proximity_sensors = []

print("[System] Booting LLM Engine...")
try:
    my_llm = GroqClient(model="openai/gpt-oss-120b")
    print("[System] LLM Engine Online!")

except Exception as e:
    print(f"[System] CRITICAL ERROR loading LLM: {e}")
    sys.exit(1)

for i in range(8):
    sensor = supervisor.getDevice(f"ps{i}")
    sensor.enable(TIME_STEP)
    proximity_sensors.append(sensor)

print(proximity_sensors)

target_node = supervisor.getFromDef("TARGET_0")
print(target_node)
if left_motor and right_motor:
    left_motor.setPosition(float("inf"))
    right_motor.setPosition(float("inf"))
    left_motor.setVelocity(0.0)
    right_motor.setVelocity(0.0)


waypoint_nodes = []
for i in range(3):
    node = supervisor.getFromDef(f"TARGET_{i}")
    if node:
        waypoint_nodes.append(node)

hardware_map = {
    "left_motor": left_motor,
    "right_motor": right_motor,
    "proximity_sensors": proximity_sensors,
}
world_tracker = WorldState(supervisor, proximity_sensors)
planner = PlannerAgent(llm_client=my_llm)  # Pass your actual LLM client here
executor = PlanExecutor(supervisor, sio, hardware_map)


# 2. Initialize the active skill
# current_skill = WanderSkill(supervisor, sio, left_motor, right_motor, proximity_sensors)
# current_skill = SpinScanSkill(
#     supervisor=supervisor,
#     sio=sio,
#     left_motor=left_motor,
#     right_motor=right_motor,
#     duration_ticks=150,
#     rotation_speed=1.5,
# )

# current_skill = AvoidObstacleSkill(
#     supervisor=supervisor,
#     sio=sio,
#     left_motor=left_motor,
#     right_motor=right_motor,
#     proximity_sensors=proximity_sensors,
# )

# current_skill = GoToTargetSkill(supervisor, sio, left_motor, right_motor, target_node)

avoid_skill = AvoidObstacleSkill(
    supervisor, sio, left_motor, right_motor, proximity_sensors
)


def is_path_blocked(sensors):
    try:
        return (sensors[7].getValue() + sensors[0].getValue()) > 300.0
    except Exception:
        return False


user_goal = "Scan the area, then move to TARGET_0."
needs_replanning = True
tick = 0

while supervisor.step(TIME_STEP) != -1:
    tick += 1

    # 1. UPDATE WORLD STATE
    world_tracker.update(active_skill=executor.current_skill)
    current_state = world_tracker.get_state()

    # 2. THE REPLANNING TRIGGER
    if needs_replanning:
        # Pause motors while thinking
        left_motor.setVelocity(0)
        right_motor.setVelocity(0)

        print("\n[Brain] Triggering Planner...")
        new_plan = planner.generate_plan(user_goal, current_state)
        executor.load_plan(new_plan)
        needs_replanning = False

    # 3. THE ARBITER (Safety Override)
    if is_path_blocked(proximity_sensors):
        # Subsumption: take over, but DON'T clear the plan yet
        avoid_skill.update()

        # Optional: If stuck for too long, set needs_replanning = True
    else:
        # 4. EXECUTE PLAN
        status = executor.update()

        if status == "DONE":
            print("[Brain] Mission Accomplished. Awaiting new orders.")
            break  # Or ask user for new goal

        elif status == "FAILED":
            print("[Brain] Plan failed! Initiating Replan...")
            needs_replanning = True

    # 5. TELEMETRY
    if tick % 15 == 0:
        sio.emit("world_state_stream", world_tracker.to_json())
