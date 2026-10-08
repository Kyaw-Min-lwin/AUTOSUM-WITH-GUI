"""Motor controller. Mission allocation and LLM calls live in Flask."""
import queue
import sys
import socketio
from controller import Supervisor
from executor import PlanExecutor
from skills import AvoidObstacleSkill
from world_state import WorldState


def run():
    supervisor = Supervisor()
    time_step = int(supervisor.getBasicTimeStep())
    agent_id = sys.argv[1] if len(sys.argv) > 1 else "epuck_1"
    mission_id = sys.argv[2] if len(sys.argv) > 2 else ""
    agent_type = "drone" if "drone" in agent_id.lower() else "ground"
    sio = socketio.Client()
    incoming = queue.SimpleQueue()

    @sio.event
    def connect():
        sio.emit("agent_log", {"agent": agent_id, "message": "Hardware online. Awaiting mission plans."})

    @sio.on("execute_plan")
    def on_execute_plan(data):
        if (data.get("agent_id") == agent_id
                and data.get("mission_id", "") == mission_id
                and data.get("plan_id")):
            # Only the simulation thread may call Webots hardware.
            incoming.put(data)

    left_motor = right_motor = None
    sensors = []
    if agent_type == "ground":
        left_motor = supervisor.getDevice("left wheel motor")
        right_motor = supervisor.getDevice("right wheel motor")
        for i in range(8):
            sensor = supervisor.getDevice(f"ps{i}")
            sensor.enable(time_step)
            sensors.append(sensor)
        for motor in (left_motor, right_motor):
            motor.setPosition(float("inf"))
            motor.setVelocity(0.0)

    hardware = {"left_motor": left_motor, "right_motor": right_motor, "proximity_sensors": sensors}
    world = WorldState(supervisor, sensors)
    # Connect before the executor emits its drone startup log.
    sio.connect("http://localhost:5000")
    executor = PlanExecutor(agent_id, supervisor, sio, hardware)
    avoid = (AvoidObstacleSkill(agent_id, supervisor, sio, left_motor, right_motor, sensors)
             if agent_type == "ground" else None)
    seen_plans = set()
    active_plan_id = None

    def report(status, plan_id, message=None):
        if sio.connected:
            sio.emit("skill_status", {"agent_id": agent_id, "mission_id": mission_id,
                                     "plan_id": plan_id, "status": status, "message": message})

    tick = 0
    try:
        while supervisor.step(time_step) != -1:
            while not incoming.empty():
                data = incoming.get_nowait()
                plan_id = data["plan_id"]
                if plan_id in seen_plans:
                    continue
                seen_plans.add(plan_id)
                if active_plan_id is not None:
                    report("FAILED", plan_id, "Robot is already executing a plan")
                    continue
                active_plan_id = plan_id
                executor.load_plan(data)
                report("RUNNING", plan_id)

            world.update(active_skill=executor.current_skill)
            if tick % 15 == 0 and sio.connected:
                sio.emit("telemetry_update", {
                    "agent_id": agent_id, "mission_id": mission_id, "type": agent_type,
                    "position": supervisor.getSelf().getPosition(),
                    "world_state": world.get_state(),
                })

            blocked = avoid is not None and sensors[7].getValue() + sensors[0].getValue() > 300.0
            if blocked and executor.status == "RUNNING":
                avoid.update()
            else:
                error = None
                try:
                    status = executor.update()
                except Exception as exc:
                    executor.abort()
                    status, error = "FAILED", str(exc)
                if status in ("DONE", "FAILED"):
                    report(status, active_plan_id, error)
                    active_plan_id = None
                    executor.status = "IDLE"
            tick += 1
    finally:
        executor.abort()
        sio.disconnect()


if __name__ == "__main__":
    run()
