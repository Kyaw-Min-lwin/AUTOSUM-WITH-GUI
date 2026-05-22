import sys
import os
import socketio
from controller import Supervisor

# Import your custom classes
from world_state import WorldState
from executor import PlanExecutor
from skills import AvoidObstacleSkill
from blackboard import Blackboard
from perception_agent import PerceptionAgent
from pathfinder import AStarPathfinder

# Import LangGraph components
from langchain_groq import ChatGroq
# (The file where you put the LangGraph code)
from robot_agent import build_robot_graph

# ==========================================
# 1. WEBOTS SUPERVISOR & SOCKET.IO INIT
# ==========================================
supervisor = Supervisor()
TIME_STEP = int(supervisor.getBasicTimeStep())
sio = socketio.Client()

# ==========================================
# 2. AGENT IDENTITY (Source of agent_id, agent_type)
# ==========================================
agent_id = sys.argv[1] if len(sys.argv) > 1 else "epuck_1"
agent_type = "drone" if "drone" in agent_id.lower() else "ground"

try:
    print(f"[{agent_id.upper()}] Connecting to Command Center...")
    sio.connect("http://localhost:5000")
    sio.emit("agent_log", {"agent": agent_id, "message": "Hardware online."})
except Exception:
    pass

# ==========================================
# 3. HARDWARE INIT (Source of motors, proximity_sensors)
# ==========================================
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

# ==========================================
# 4. CLASS INSTANTIATIONS (Source of blackboard, executor, etc.)
# ==========================================
blackboard = Blackboard(supervisor)
blackboard.register_agent(agent_id, agent_type=agent_type)

world_tracker = WorldState(supervisor, proximity_sensors)
executor = PlanExecutor(agent_id, supervisor, sio, hardware_map)

avoid_skill = None
if left_motor and right_motor:
    avoid_skill = AvoidObstacleSkill(
        agent_id, supervisor, sio, left_motor, right_motor, proximity_sensors
    )

global_pathfinder = AStarPathfinder(cell_size=0.1, obstacle_padding=0.25)
perception = PerceptionAgent(blackboard, sio)

# Setup global user goal
blackboard.set_user_goal("All the robots will follow one epuck")
if agent_type == "drone":
    blackboard.set_mission_status("executing")
else:
    blackboard.set_mission_status("needs_objectives")

# ==========================================
# 5. LANGGRAPH INIT (Source of llm, agent_graph)
# ==========================================
print(f"[{agent_id.upper()}] Booting LangGraph Engine...")
llm = ChatGroq(
    model="llama3-70b-8192",
    temperature=0.0,
    api_key=os.getenv("GROQ_API_KEY")
)

agent_graph = build_robot_graph()

# ==========================================
# 6. THE MAIN LOOP
# ==========================================
tick = 0
while supervisor.step(TIME_STEP) != -1:
    tick += 1
    blackboard.increment_tick()

    # Package all the variables we initialized above into the StateDict!
    current_state = {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "blackboard": blackboard,
        "executor": executor,
        "avoid_skill": avoid_skill,
        "proximity_sensors": proximity_sensors,
        "pathfinder": global_pathfinder,
        "llm": llm,
        "world_tracker": world_tracker,
        "perception": perception,
        "supervisor": supervisor,
        "evading": False  # Always starts False at the beginning of a tick
    }

    # Pass the state into the graph. The graph will mutate the state
    # (e.g., update the blackboard, change 'evading' to True, etc.)
    agent_graph.invoke(current_state)

    # Telemetry
    if tick % 15 == 0:
        sio.emit("world_state_stream", blackboard.to_json())
