import random
import math
from pathfinder import AStarPathfinder


class BaseSkill:

    def __init__(self, agent_id, supervisor, sio, left_motor, right_motor):
        self.agent_id = agent_id
        self.supervisor = supervisor
        self.sio = sio
        self.left_motor = left_motor
        self.right_motor = right_motor

    def start(self):
        """Lifecycle method called when skill is first activated."""
        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": f"Activating skill: {self.__class__.__name__}",
                },
            )

    def update(self):
        pass

    def stop(self):
        self.set_wheel_speeds(0.0, 0.0)
        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": f"Terminated skill: {self.__class__.__name__}",
                },
            )

    def is_complete(self):
        return False

    def set_wheel_speeds(self, left: float, right: float):
        if self.left_motor and self.right_motor:
            self.left_motor.setVelocity(left)
            self.right_motor.setVelocity(right)


class SpinScanSkill(BaseSkill):
    """
    Executes a timed rotation in place.
    Completes automatically after X ticks, allowing the supervisor to chain the next skill.
    """

    def __init__(
        self,
        agent_id,
        supervisor,
        sio,
        left_motor,
        right_motor,
        duration_ticks: int = 100,
        rotation_speed: float = 1.5,
    ):
        super().__init__(agent_id, supervisor, sio, left_motor, right_motor)
        self.duration_ticks = duration_ticks
        self.rotation_speed = rotation_speed
        self.current_tick = 0

    def start(self):
        """Reset internal state and log activation."""
        super().start()
        self.current_tick = 0

    def update(self):
        self.set_wheel_speeds(self.rotation_speed, -self.rotation_speed)
        self.current_tick += 1

    def is_complete(self):
        return self.current_tick >= self.duration_ticks


class WanderSkill(BaseSkill):
    def __init__(
        self,
        agent_id,
        supervisor,
        sio,
        left_motor,
        right_motor,
        proximity_sensors=None,
        forward_speed=2.5,
        turn_speed=2.0,
        obstacle_threshold=150.0,
        duration_ticks=300,
    ):
        super().__init__(agent_id, supervisor, sio, left_motor, right_motor)
        self.proximity_sensors = proximity_sensors or []
        self.forward_speed = forward_speed
        self.turn_speed = turn_speed
        self.obstacle_threshold = obstacle_threshold
        self.state = "forward"
        self.turn_ticks_remaining = 0
        self.duration_ticks = duration_ticks
        self.current_tick = 0

    def start(self):
        super().start()
        self.current_tick = 0
        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": "Exploration routine initialized.",
                },
            )

    def update(self):
        self.current_tick += 1
        if self.current_tick > self.duration_ticks:
            self.set_wheel_speeds(0.0, 0.0)
            return

        if self.state == "turning":
            self.set_wheel_speeds(self.turn_speed, -self.turn_speed)
            self.turn_ticks_remaining -= 1
            if self.turn_ticks_remaining <= 0:
                self.state = "forward"
                if self.sio:
                    self.sio.emit(
                        "agent_log",
                        {
                            "agent": self.agent_id,
                            "message": "Turn complete. Resuming forward.",
                        },
                    )
            return

        if self.detect_obstacle():
            self.state = "turning"
            self.turn_ticks_remaining = random.randint(15, 45)
            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {
                        "agent": self.agent_id,
                        "message": f"Obstacle detected. Evading ({self.turn_ticks_remaining} ticks).",
                    },
                )
            return

        self.set_wheel_speeds(self.forward_speed, self.forward_speed)

    def is_complete(self):
        return self.current_tick >= self.duration_ticks

    def detect_obstacle(self):
        if not self.proximity_sensors:
            return False
        for sensor in self.proximity_sensors:
            try:
                if sensor.getValue() > self.obstacle_threshold:
                    return True
            except Exception:
                continue
        return False


class AvoidObstacleSkill(BaseSkill):

    def __init__(
        self,
        agent_id,
        supervisor,
        sio,
        left_motor,
        right_motor,
        proximity_sensors,
        obstacle_threshold=300.0,  # Increased threshold for sum
        forward_speed=2.5,
        turn_speed=2.0,
    ):
        super().__init__(agent_id, supervisor, sio, left_motor, right_motor)
        self.proximity_sensors = proximity_sensors
        self.obstacle_threshold = obstacle_threshold
        self.forward_speed = forward_speed
        self.turn_speed = turn_speed

    def start(self):
        super().start()
        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": "Reactive collision avoidance online.",
                },
            )

    def update(self):
        sensor_values = self.read_sensors()

        # Safety check to prevent IndexErrors
        if len(sensor_values) < 8:
            self.set_wheel_speeds(0, 0)
            return

        left_strength = sensor_values[5] + sensor_values[6] + sensor_values[7]
        right_strength = sensor_values[0] + sensor_values[1] + sensor_values[2]
        front_strength = sensor_values[7] + sensor_values[0]

        if front_strength > self.obstacle_threshold:
            if left_strength > right_strength:
                self.set_wheel_speeds(self.turn_speed, -self.turn_speed)
            else:
                self.set_wheel_speeds(-self.turn_speed, self.turn_speed)
            return

        if left_strength > self.obstacle_threshold:
            self.set_wheel_speeds(self.forward_speed, self.forward_speed * 0.3)
            return

        if right_strength > self.obstacle_threshold:
            self.set_wheel_speeds(self.forward_speed * 0.3, self.forward_speed)
            return

        self.set_wheel_speeds(self.forward_speed, self.forward_speed)

    def read_sensors(self):
        values = []
        for sensor in self.proximity_sensors:
            try:
                values.append(sensor.getValue())
            except Exception:
                values.append(0.0)
        return values


class GoToTargetSkill(BaseSkill):
    def __init__(
        self,
        agent_id,
        supervisor,
        sio,
        left_motor,
        right_motor,
        target_node,
        forward_speed=3.0,
        turn_speed=1.5,
        angle_tolerance=0.2,
        distance_tolerance=0.1,
    ):
        super().__init__(agent_id, supervisor, sio, left_motor, right_motor)
        self.target_node = target_node
        self.forward_speed = forward_speed
        self.turn_speed = turn_speed
        self.angle_tolerance = angle_tolerance
        self.distance_tolerance = distance_tolerance

        self.waypoint_tolerance = 0.1
        self.path = []

        self.arrived = False
        self.failed = False
        self.ticks_elapsed = 0
        self.max_ticks = 2500

    def start(self):
        super().start()

        robot_pos = self.get_robot_position()
        target_pos = self.get_target_position()

        obstacle_positions = []
        root = self.supervisor.getRoot()
        children = root.getField("children")
        for i in range(children.getCount()):
            node = children.getMFNode(i)
            if node and node.getDef() and node.getDef().startswith("WALL_"):
                pos = node.getPosition()
                obstacle_positions.append((pos[0], pos[1]))

        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": f"Calculating A* route around {len(obstacle_positions)} obstacles...",
                },
            )

        pathfinder = AStarPathfinder(cell_size=0.1, obstacle_padding=0.04)
        self.path = pathfinder.find_path(robot_pos, target_pos, obstacle_positions)

        if not self.path:
            self.failed = True
            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {
                        "agent": self.agent_id,
                        "message": "CRITICAL: No valid path to target.",
                    },
                )
        else:
            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {
                        "agent": self.agent_id,
                        "message": f"Path found with {len(self.path)} steps. Engaging motors.",
                    },
                )

    def update(self):
        self.ticks_elapsed += 1

        if self.ticks_elapsed > self.max_ticks:
            self.failed = True
            self.set_wheel_speeds(0.0, 0.0)
            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {"agent": self.agent_id, "message": "Navigation timed out."},
                )
            return

        if self.arrived or self.failed:
            self.set_wheel_speeds(0.0, 0.0)
            return

        robot_pos = self.get_robot_position()
        robot_heading = self.get_robot_heading()

        if len(self.path) > 0:
            current_target = self.path[0]
            current_tolerance = self.waypoint_tolerance
        else:
            current_target = self.get_target_position()
            current_tolerance = self.distance_tolerance

        dx = current_target[0] - robot_pos[0]
        dy = current_target[1] - robot_pos[1]
        distance = math.sqrt(dx**2 + dy**2)

        if distance < current_tolerance:
            if len(self.path) > 0:
                self.path.pop(0)
                self.set_wheel_speeds(0.0, 0.0)
                return
            else:
                self.arrived = True
                self.set_wheel_speeds(0.0, 0.0)
                if self.sio:
                    self.sio.emit(
                        "agent_log",
                        {
                            "agent": self.agent_id,
                            "message": "Destination reached successfully.",
                        },
                    )
                return

        # =====================================
        # ROTATE TOWARD CURRENT TARGET
        # =====================================
        target_angle = math.atan2(dy, dx)
        angle_error = self.normalize_angle(target_angle - robot_heading)

        if abs(angle_error) > self.angle_tolerance:
            if angle_error > 0:
                self.set_wheel_speeds(-self.turn_speed, self.turn_speed)  # Turn left
            else:
                self.set_wheel_speeds(self.turn_speed, -self.turn_speed)  # Turn right
            return

        # =====================================
        # MOVE FORWARD
        # =====================================
        self.set_wheel_speeds(self.forward_speed, self.forward_speed)

    def is_complete(self):
        return self.arrived or self.failed

    # ==================================================
    # HELPERS
    # ==================================================

    def get_robot_position(self):
        pos = self.supervisor.getSelf().getPosition()
        return (pos[0], pos[1])

    def get_target_position(self):
        pos = self.target_node.getPosition()
        return (pos[0], pos[1])

    def get_robot_heading(self):

        node = self.supervisor.getSelf()

        orientation = node.getOrientation()

        heading = math.atan2(orientation[3], orientation[0])

        return heading

    def normalize_angle(self, angle):
        while angle > math.pi:
            angle -= 2 * math.pi
        while angle < -math.pi:
            angle += 2 * math.pi
        return angle


class PatrolSkill(BaseSkill):
    def __init__(
        self,
        agent_id,
        supervisor,
        sio,
        left_motor,
        right_motor,
        waypoint_nodes,
        goto_skill_class,
    ):
        super().__init__(agent_id, supervisor, sio, left_motor, right_motor)
        self.waypoint_nodes = waypoint_nodes
        self.goto_skill_class = goto_skill_class
        self.current_waypoint_index = 0
        self.active_navigation_skill = None

    def start(self):
        super().start()
        if not self.waypoint_nodes:
            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {"agent": self.agent_id, "message": "Patrol failed: No waypoints."},
                )
            return

        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": "PatrolSkill",
                    "message": f"Patrol route initialized with {len(self.waypoint_nodes)} waypoints.",
                },
            )

        self.activate_current_waypoint()

    def update(self):
        if not self.active_navigation_skill:
            return

        self.active_navigation_skill.update()

        # =====================================
        # WAYPOINT REACHED
        # =====================================
        if self.active_navigation_skill.is_complete():
            self.current_waypoint_index += 1

            if self.current_waypoint_index >= len(self.waypoint_nodes):
                self.current_waypoint_index = 0
                if self.sio:
                    self.sio.emit(
                        "agent_log",
                        {
                            "agent": self.agent_id,
                            "message": "Patrol loop completed. Restarting route.",
                        },
                    )

            self.activate_current_waypoint()

    def activate_current_waypoint(self):
        target_node = self.waypoint_nodes[self.current_waypoint_index]

        if self.sio:
            self.sio.emit(
                "agent_log",
                {
                    "agent": self.agent_id,
                    "message": f"Navigating to waypoint {self.current_waypoint_index + 1}",
                },
            )

        self.active_navigation_skill = self.goto_skill_class(
            agent_id=self.agent_id,
            supervisor=self.supervisor,
            sio=self.sio,
            left_motor=self.left_motor,
            right_motor=self.right_motor,
            target_node=target_node,
        )
        self.active_navigation_skill.start()


class AerialScanSkill(BaseSkill):
    def __init__(self, agent_id, supervisor, sio, left_motor=None, right_motor=None):
        super().__init__(agent_id, supervisor, sio, left_motor, right_motor)
        self.drone_node = self.supervisor.getFromDef(agent_id.upper())
        self.translation_field = self.drone_node.getField("translation")
        self.target_altitude = 3.0
        self.ascent_speed = 0.015
        self._is_complete = False

    def start(self):
        super().start()
        if self.sio:
            self.sio.emit(
                "agent_log",
                {"agent": self.agent_id, "message": "Initiating aerial ascent."},
            )

    def update(self):
        position = self.translation_field.getSFVec3f()
        x = position[0]
        y = position[1]
        z = position[2]

        # CHANGED: Webots ENU coordinates map altitude to the Z axis!
        if z < self.target_altitude:
            z += self.ascent_speed
            self.translation_field.setSFVec3f([x, y, z])
        else:
            self._is_complete = True
            if self.sio:
                self.sio.emit(
                    "agent_log",
                    {
                        "agent": self.agent_id,
                        "message": "Aerial scan altitude reached.",
                    },
                )

    def is_complete(self):
        return self._is_complete
