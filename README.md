# AutoSim — robot missions from a visual map

Draw an arena, type a mission, and run E-puck ground robots and a Crazyflie
drone in Webots. The desktop app contains a Three.js map editor, an embedded
Webots stream, and a live agent console.

## Active architecture

The default path is now **centralized**:

1. Electron sends the exact user goal and map to Flask over Socket.IO.
2. Flask creates a fresh mission ID and registers the complete map's robot roster.
3. The world builder generates a Webots world using the `autosim_agent` controller.
4. Each robot reports telemetry tagged with its mission and robot IDs.
5. With a drone, ground planning waits for its 0.8m recon altitude and for every
   expected robot to report in. Without a drone, planning uses the supplied map.
6. One LangGraph Strategist allocates objectives across the full ground swarm.
7. Each ready robot gets an isolated Navigator tool conversation. Tools read
   authoritative coordinates, check A* reachability, and validate the chosen skill.
8. Flask dispatches fresh plans with unique plan IDs. Webots executes motor
   skills locally; socket callbacks queue work for the simulation thread.
9. A matching completion advances an objective once. Failed physical actions
   retry the same objective up to three attempts, then mark the mission failed.

LLM calls run in a backend worker rather than the Webots controller loop.
Incoming telemetry stays live while planning. A new run resets mission state;
results, telemetry, and completions from an older run are ignored.

`backend/controllers/autosim_supervisor/` retains the legacy per-robot LLM
implementation for reference. Generated worlds no longer use it.

## Stack

- Electron, JavaScript, Three.js, Tailwind CSS
- Python, Flask, Flask-SocketIO, python-socketio
- LangGraph, LangChain, Groq (`openai/gpt-oss-120b` by default)
- Pydantic for action shape validation; JSON-compatible shared graph state
- Webots R2025a; custom A* navigation and motor skills
- An optional Gemini client remains in the legacy controller

## Setup

Install Python 3.11+, Node.js/npm, and Webots R2025a. Create a **fresh**
environment; the old tracked `venv/` directory is not portable.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
npm install
```

Copy `env.example` to `.env` in the repository root and set `GROQ_API_KEY`.
Optionally set `GROQ_MODEL` and `WEBOTS_EXECUTABLE` (default: `webots` on PATH).
The Gemini key is only needed for the legacy Gemini client.

Configure Webots to use a Python interpreter with `python-socketio` and
`requests` installed, preferably the same environment as the backend.
Set the Python command in Webots Preferences, or use a local
`backend/controllers/autosim_agent/runtime.ini`:

```ini
[python]
COMMAND = /absolute/path/to/your/python
```

See the [Webots Python setup guide](https://github.com/cyberbotics/webots/blob/R2025a/docs/guide/using-python.md).

```sh
npm start
```

Flask listens on localhost:5000; Webots streaming uses localhost:1234.

## Use

Place walls, targets, E-pucks, and optionally a drone inside the arena.
Left-click/drag places objects; right-drag orbits; middle-drag pans; the wheel
zooms. If no E-puck is placed, one is added at the origin.

Enter a goal such as "Send each robot to a different target" and execute.
Finite objectives complete; following, patrol, and drone hover are continuous.
The backend emits `mission_status` and `glass_brain_update` events for clients
that need structured progress.

## Tests

```sh
python -m unittest discover -s tests -v
```

The suite exercises world/controller wiring, mission isolation, registration,
recon gating, real LangGraph tool loops, isolated robot conversations, Socket.IO
goal/telemetry/plan/completion flow, and failure handling. It substitutes model
responses and hardware where appropriate; no API key or Webots is required.

An optional real-simulator check is available with
`python tests/manual_webots_smoke.py`. It requires Webots on PATH (or
`WEBOTS_EXECUTABLE`) and a free localhost:5000. It uses a temporary project
and scripted model responses, and fails if the mission does not finish within
50 seconds. It does not exercise the Electron window or a live cloud model.

## Current limits

- Drone motion is scripted using supervisor position updates and physics resets.
  Recon uses simulator/map ground truth, not camera-based object recognition.
- A* uses static obstacles; this is not a validated real-robot safety system.
- LLM planning quality still needs live-model evaluation on representative missions.
- Maps and run history are not persisted; following/patrol require a new run or
  stopping the simulator to end.
- The Electron security settings and tracked legacy virtual environment still
  need a separate cleanup before distribution.
