import sys
import socketio
from controller import Supervisor
from world_state import WorldState
from llm_client import GroqClient
from navigator_agent import NavigatorAgent
from mission_director import MissionDirector
from executor import PlanExecutor
from skills import AvoidObstacleSkill
from blackboard import Blackboard
from perception_agent import PerceptionAgent
from pathfinder import AStarPathfinder

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
executor = PlanExecutor(supervisor, sio, hardware_map)
avoid_skill = AvoidObstacleSkill(
    supervisor, sio, left_motor, right_motor, proximity_sensors
)
global_pathfinder = AStarPathfinder(cell_size=0.1, obstacle_padding=0.25)
perception = PerceptionAgent(blackboard, sio)
director = MissionDirector(blackboard, my_llm, sio)

# Inject the Tool into the Navigator!
navigator = NavigatorAgent(llm_client=my_llm, pathfinder=global_pathfinder, sio=sio)


def is_path_blocked(sensors):
    try:
        return (sensors[7].getValue() + sensors[0].getValue()) > 300.0
    except Exception:
        return False


# Initialize Mission on the Blackboard
blackboard.set_user_goal("Scan the area, then find and move to TARGET_0.")
blackboard.set_mission_status("needs_objectives")

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

    if blackboard.state["mission"]["status"] == "needs_objectives":
        left_motor.setVelocity(0)
        right_motor.setVelocity(0)

        print("\n[Brain] Waking Mission Director...")
        director.generate_objectives()
        blackboard.set_mission_status("needs_planning")

    elif blackboard.state["mission"]["status"] == "needs_planning":
        left_motor.setVelocity(0)
        right_motor.setVelocity(0)

        current_obj = blackboard.state["mission"]["current_objective"]
        if current_obj:
            # We now pass the ENTIRE snapshot! The Navigator handles its own extraction.
            new_plan = navigator.generate_plan(blackboard.snapshot())

            blackboard.set_active_plan(new_plan.get("plan", []))
            executor.load_plan(new_plan)
            blackboard.set_mission_status("executing")
        else:
            blackboard.set_mission_status("idle")

    # THE ARBITER
    if is_path_blocked(proximity_sensors):
        avoid_skill.update()
        blackboard.update_robot_state(status="evading")
    elif blackboard.state["mission"]["status"] == "executing":
        status = executor.update()

        if status == "DONE":
            print("[Executor] Objective complete.")

            objectives = blackboard.state["mission"]["objectives"]
            if objectives:
                objectives.pop(0)

            if objectives:
                blackboard.set_current_objective(objectives[0])
                blackboard.set_mission_status("needs_planning")
            else:
                blackboard.set_mission_status("idle")
                blackboard.set_current_objective(None)
                print(
                    "[Brain] All Mission Objectives Accomplished. Awaiting new orders."
                )

        elif status == "FAILED":
            # Total failure. Log it and ask the Director to rethink the whole strategy.
            blackboard.remember_event(
                f"Objective '{blackboard.state['mission']['current_objective']}' failed."
            )
            print("[Executor] Plan failed! Triggering Strategic Replan...")
            blackboard.set_mission_status("needs_objectives")

    # 7. TELEMETRY
    if tick % 15 == 0:
        sio.emit("world_state_stream", blackboard.to_json())
