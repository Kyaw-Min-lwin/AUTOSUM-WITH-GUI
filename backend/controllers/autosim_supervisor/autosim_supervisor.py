import sys
import socketio
from controller import Supervisor
from world_state import WorldState
from llm_client import GroqClient
from planner import PlannerAgent
from executor import PlanExecutor
from skills import AvoidObstacleSkill
from blackboard import Blackboard
from perception_agent import PerceptionAgent

supervisor = Supervisor()
TIME_STEP = int(supervisor.getBasicTimeStep())
sio = socketio.Client()

try:
    print("[E-PUCK] Attempting to connect to Flask Command Center...")
    sio.connect("http://localhost:5000")
except Exception as e:
    sys.exit(1)


@sio.event
def connect():
    sio.emit("agent_log", {"agent": "E-Puck", "message": "Hardware online."})


# 1. Initialize hardware
left_motor = supervisor.getDevice("left wheel motor")
right_motor = supervisor.getDevice("right wheel motor")
proximity_sensors = []

for i in range(8):
    sensor = supervisor.getDevice(f"ps{i}")
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

print("[System] Booting LLM Engine...")
try:
    my_llm = GroqClient(model="openai/gpt-oss-120b")
except Exception as e:
    sys.exit(1)


blackboard = Blackboard(supervisor)
world_tracker = WorldState(supervisor, proximity_sensors)
perception = PerceptionAgent(blackboard, sio)
planner = PlannerAgent(llm_client=my_llm)
executor = PlanExecutor(supervisor, sio, hardware_map)
avoid_skill = AvoidObstacleSkill(
    supervisor, sio, left_motor, right_motor, proximity_sensors
)


def is_path_blocked(sensors):
    try:
        return (sensors[7].getValue() + sensors[0].getValue()) > 300.0
    except Exception:
        return False


# Initialize Mission on the Blackboard
blackboard.set_user_goal("Scan the area, then move to TARGET_0.")
blackboard.set_mission_status("needs_planning")

tick = 0


# ==========================================
# THE AGENTIC LOOP
while supervisor.step(TIME_STEP) != -1:
    tick += 1
    blackboard.increment_tick()

    # 1. RAW PHYSICS -> BLACKBOARD
    world_tracker.update(active_skill=executor.current_skill)
    raw_state = world_tracker.get_state()

    # Update Blackboard with live physical data
    blackboard.set_world_state(raw_state)
    blackboard.update_robot_state(
        position=raw_state["robot"]["position"],
        heading=raw_state["robot"]["heading"],
        status=executor.status,
    )

    perception.update()

    # 2. THE REPLANNING TRIGGER (Reading from Blackboard)
    if blackboard.state["mission"]["status"] == "needs_planning":

        # Pause motors while "thinking"
        left_motor.setVelocity(0)
        right_motor.setVelocity(0)

        print("\n[Brain] Triggering Planner...")
        new_plan = planner.generate_plan(
            blackboard.state["mission"]["user_goal"], blackboard.snapshot()
        )

        # Write the new plan to the Blackboard and Executor
        blackboard.set_active_plan(new_plan.get("plan", []))
        executor.load_plan(new_plan)
        blackboard.set_mission_status("executing")

    # 3. THE ARBITER (Safety Override)
    if is_path_blocked(proximity_sensors):
        avoid_skill.update()
        blackboard.update_robot_state(status="evading")
    else:
        # 4. EXECUTE PLAN
        status = executor.update()

        if status == "DONE":
            blackboard.set_mission_status("idle")
            print("[Brain] Mission Accomplished. Awaiting new orders.")
            break

        elif status == "FAILED":
            blackboard.remember_event(
                f"Plan failed during skill: {executor.current_skill.__class__.__name__}"
            )
            print("[Brain] Plan failed! Logging to memory and initiating Replan...")
            blackboard.set_mission_status("needs_planning")

    # 5. TELEMETRY STREAMING
    if tick % 15 == 0:
        sio.emit("world_state_stream", blackboard.to_json())
