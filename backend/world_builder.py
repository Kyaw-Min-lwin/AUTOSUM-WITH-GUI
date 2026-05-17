import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_wbt(map_data: dict, filepath: str = "worlds/temp_run.wbt"):
    """
    Translates JSON map coordinates into a valid Webots .wbt file.
    """
    full_path = os.path.join(BACKEND_DIR, filepath)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    SCALE = 0.1
    wbt_content = [
        "#VRML_SIM R2025a utf8",
        'EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/backgrounds/protos/TexturedBackground.proto"',
        'EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/backgrounds/protos/TexturedBackgroundLight.proto"',
        'EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/floors/protos/RectangleArena.proto"',
        'EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/robots/gctronic/e-puck/protos/E-puck.proto"',
        'EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/robots/bitcraze/crazyflie/protos/Crazyflie.proto"',
        # Explicitly define the ENU coordinate system (X, Y = floor, Z = up)
        'Project { controllerDir "../controllers" }',
        'WorldInfo { basicTimeStep 32 coordinateSystem "ENU" }',
        "Viewpoint { position 0 -3 1.5 orientation 0 0 1 1.57 }",
        "TexturedBackground {}",
        "TexturedBackgroundLight {}",
        f"RectangleArena {{ floorSize {20 * SCALE} {20 * SCALE} }}",
    ]

    # 1. Walls
    for i, wall in enumerate(map_data.get("walls", [])):
        # Apply integer snapping AND the scale multiplier
        wx = round(wall.get("x", 0)) * SCALE
        wy = round(wall.get("z", 0)) * SCALE  # JS Z maps to Webots Y
        wz = 0.5 * SCALE  # Height is half the scaled box size
        wbt_content.append(f"""
        DEF WALL_{i} Solid {{
            translation {wx} {wy} {wz}
            name "wall_{i}"
            children [
                Shape {{
                    appearance PBRAppearance {{
                        baseColor 0.5 0.5 0.5
                        roughness 1
                        metalness 0
                    }}
                    geometry Box {{ size {SCALE} {SCALE} {SCALE} }}
                }}
            ]
            boundingObject Box {{ size {SCALE} {SCALE} {SCALE} }}
        }}""")

    # 2. Targets
    for i, target in enumerate(map_data.get("targets", [])):
        wx = round(target.get("x", 0)) * SCALE
        wy = round(target.get("z", 0)) * SCALE
        wz = 0.5 * SCALE
        r = 0.3 * SCALE
        wbt_content.append(f"""
        DEF TARGET_{i} Solid  {{
            translation {wx} {wy} {wz}
            name "target_{i}"
            children [
                Shape {{
                    appearance PBRAppearance {{
                        baseColor 0.9 0.6 0.1
                        roughness 0.5
                        metalness 0
                    }}
                    geometry Cylinder {{ height {SCALE} radius {r} }}
                }}
            ]
        }}""")

    # 3. E-pucks (Swarm)
    for epuck in map_data.get("epucks", []):
        epuck_id = epuck.get("id", "epuck_0")

        # FIX: Apply SCALE and map JS Z to Webots Y
        ex = round(epuck.get("x", 0)) * SCALE
        ey = round(epuck.get("z", 0)) * SCALE

        # FIX: Use .append() instead of +=
        wbt_content.append(f"""
        DEF {epuck_id.upper()} E-puck {{
            translation {ex} {ey} 0.01
            rotation 0 0 1 0
            controller "autosim_supervisor"
            controllerArgs [ "{epuck_id}" ]
            name "{epuck_id}"
            supervisor TRUE
        }}""")

    # 4. Drone
    drone = map_data.get("drone")
    if drone:
        drone_id = drone.get("id", "drone_1")

        # FIX: Apply SCALE and map JS Z to Webots Y
        dx = round(drone.get("x", 0)) * SCALE
        dy = round(drone.get("z", 0)) * SCALE

        # FIX: Use .append() instead of +=
        wbt_content.append(f"""
        DEF {drone_id.upper()} Crazyflie {{
            translation {dx} {dy} 0.2
            rotation 0 0 1 0
            controller "autosim_supervisor"
            controllerArgs [ "{drone_id}" ]
            name "{drone_id}"
            supervisor TRUE
        }}""")
    # Write file
    full_path = os.path.join(BACKEND_DIR, filepath)
    full_path = os.path.abspath(full_path)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write("\n".join(wbt_content))

    return full_path
