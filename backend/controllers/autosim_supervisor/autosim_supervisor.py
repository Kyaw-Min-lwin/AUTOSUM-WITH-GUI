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

# ==========================================
# MULTI-AGENT IDENTITY ASSIGNMENT
# ==========================================
# Read the controllerArgs passed from world_builder.py
agent_id = sys.argv[1] if len(sys.argv) > 1 else "epuck_1"
agent_type = "drone" if "drone" in agent_id.lower() else "ground"

try:
    print(f"[{agent_id.upper()}] Attempting to connect to Flask Command Center...")
    sio.connect("http://localhost:5000")
except Exception as e:
    sys.exit(1)


@sio.event
def connect():
    # Tag telemetry with specific agent identity
    sio.emit("agent_log", {"agent": agent_id, "message": "Hardware online."})


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

# Build the map (Drone will just have None/Empty lists, which is perfectly safe!)
hardware_map = {
    "left_motor": left_motor,
    "right_motor": right_motor,
    "proximity_sensors": proximity_sensors,
}

print(f"[{agent_id.upper()}] Booting LLM Engine...")
try:
    my_llm = GroqClient(model="openai/gpt-oss-120b")
except Exception as e:
    sys.exit(1)

# ==========================================
# AGENT INSTANTIATIONS
# ==========================================
blackboard = Blackboard(supervisor)

# Register THIS specific agent's memory partitions
blackboard.register_agent(agent_id, agent_type=agent_type)

world_tracker = WorldState(supervisor, proximity_sensors)
executor = PlanExecutor(agent_id, supervisor, sio, hardware_map)

if left_motor and right_motor:
    avoid_skill = AvoidObstacleSkill(
        agent_id, supervisor, sio, left_motor, right_motor, proximity_sensors
    )

global_pathfinder = AStarPathfinder(cell_size=0.1, obstacle_padding=0.25)

perception = PerceptionAgent(blackboard, sio)
director = MissionDirector(blackboard, my_llm, sio)
navigator = NavigatorAgent(llm_client=my_llm, pathfinder=global_pathfinder, sio=sio)


def is_path_blocked(sensors):
    try:
        if len(sensors) >= 8:
            return (sensors[7].getValue() + sensors[0].getValue()) > 300.0
        return False
    except Exception:
        return False


# Setup global user goal
blackboard.set_user_goal("All the robots will follow one epuck")
if agent_type == "drone":
    # The drone skips planning and immediately runs its auto-deployed AerialScanSkill
    blackboard.set_mission_status("executing")
else:
    # Ground units wait for the Director and the Drone
    blackboard.set_mission_status("needs_objectives")

tick = 0

# ==========================================
# THE HIERARCHICAL AGENTIC LOOP
# ==========================================
while supervisor.step(TIME_STEP) != -1:
    tick += 1
    blackboard.increment_tick()

    # 1. RAW PHYSICS -> BLACKBOARD
    world_tracker.update(active_skill=executor.current_skill)
    raw_state = world_tracker.get_state()
    blackboard.set_world_state(raw_state)
    # Update Robot state specific to THIS agent
    blackboard.update_robot_state(
        agent_id,
        position=raw_state["robot"]["position"],
        heading=raw_state["robot"]["heading"],
        status=executor.status,
    )
    # 2. WAKE THE ORACLE (Perception updates Semantic State)
    perception.update(agent_id)
    perception.check_aerial_recon(blackboard, supervisor, agent_id)

    # 3. MISSION DIRECTOR (Strategy)
    if blackboard.state["mission"]["status"] == "needs_objectives":
        if left_motor and right_motor:
            left_motor.setVelocity(0)
            right_motor.setVelocity(0)

        print(f"\n[{agent_id.upper()} Brain] Waking Mission Director...")
        director.generate_objectives(agent_id)
        blackboard.set_mission_status("needs_planning")

    # 4. NAVIGATOR AGENT (Tactics)
    elif blackboard.state["mission"]["status"] == "needs_planning":
        if left_motor and right_motor:
            left_motor.setVelocity(0)
            right_motor.setVelocity(0)

        # Query Blackboard strictly for THIS agent's objective
        current_obj = blackboard.state["mission"]["current_objectives"].get(agent_id)

        if current_obj:
            print(
                f"\n[{agent_id.upper()} Brain] Waking Navigator for objective: {current_obj}"
            )

            new_plan = navigator.generate_plan(blackboard.snapshot(), agent_id)

            # Store active plan specific to THIS agent
            blackboard.set_active_plan(agent_id, new_plan.get("plan", []))
            executor.load_plan(new_plan)
            blackboard.set_mission_status("executing")
        else:
            blackboard.set_mission_status("idle")

    # 5. ARBITER (Safety)
    elif is_path_blocked(proximity_sensors):
        avoid_skill.update()
        blackboard.update_robot_state(agent_id, status="evading")

    # 6. EXECUTOR (Motors)
    elif blackboard.state["mission"]["status"] == "executing":
        status = executor.update()

        if status == "DONE":
            print(f"[{agent_id.upper()} Executor] Objective complete.")

            if agent_type == "drone":
                blackboard.set_mission_status("idle")
                print(
                    f"[{agent_id.upper()} Brain] Aerial Recon complete. Holding position."
                )
            else:
                # Pop the completed objective for THIS agent
                objectives = blackboard.state["mission"]["objectives"].get(agent_id, [])
                if objectives:
                    objectives.pop(0)

                if objectives:
                    blackboard.set_current_objective(agent_id, objectives[0])
                    blackboard.set_mission_status("needs_planning")
                else:
                    blackboard.set_mission_status("idle")
                    blackboard.set_current_objective(agent_id, None)
                    print(
                        f"[{agent_id.upper()} Brain] All assigned Mission Objectives Accomplished."
                    )

        elif status == "FAILED":
            current_obj = blackboard.state["mission"]["current_objectives"].get(
                agent_id
            )
            blackboard.remember_event(agent_id, f"Objective '{current_obj}' failed.")
            print(
                f"[{agent_id.upper()} Executor] Plan failed! Triggering Strategic Replan..."
            )
            blackboard.set_mission_status("needs_objectives")

    # 7. TELEMETRY
    if tick % 15 == 0:
        sio.emit("world_state_stream", blackboard.to_json())
