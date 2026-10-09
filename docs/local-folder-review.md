# Local folder integration review

Source: the user's working copy at `D:/AutoSim_Desktop gui/`.
Compared with original main `5b77070` and branch `480ac95`.
The source folder, its Git history, local environment, and secrets were not modified.

## Retained and adapted

| Local improvement | Integration |
| --- | --- |
| GoToTargetSkill accepts a target ID | Resolve the ID when the skill starts, on the simulation thread. Normalize target IDs to uppercase and fail cleanly for missing targets. |
| PatrolSkill carries waypoint IDs | Resolve each waypoint on activation instead of retaining all Webots node handles. Missing or failed waypoints fail the patrol rather than being skipped. Successful patrols remain continuous. |
| Tool accepts waypoint_ids | Accept this as an alias for the branch's canonical waypoints field. Validate every waypoint; reject conflicting use of both names. |
| Obstacle padding raised from 0.04m to 0.08m | Apply the same setting to central feasibility checks and motor navigation. A geometric regression test checks both routes avoid the inflated wall cells. This remains a grid approximation, not a real-robot safety guarantee. |
| Virtual-environment ignore rules | Ignore new files in venv/ and .venv/. Already tracked environment files are unchanged. |
| websocket-client dependency | Declare the client transport dependency explicitly without copying the full machine-specific package freeze. |

## Useful changes already covered by the branch

- The correctly named autosim_agent controller and world-builder selection.
- Ground-only missions without waiting for an absent drone.
- Preserving current robot telemetry while an LLM call is in progress.
- Per-robot dispatch flag checks and skipping robots with empty objectives.
- Ending a tool loop after successful action dispatch.
- JSON-safe state emission, consistent robot IDs, and coordinate context for planning.

The branch also retains isolated Navigator conversations, one mission ID per
run, unique plan IDs, and a simulation-thread queue for incoming commands.

## Not copied

- The local Navigator prompt uses X/Z for ground navigation and explicitly
  tells the model to supply an empty obstacle list. Generated worlds use ENU
  coordinates: X/Y is the floor and Z is altitude. The branch's tools retain
  authoritative X/Y positions and actual wall geometry.
- Local readiness/recon handlers lack mission isolation, and the ready payload's
  has_drone key does not match the backend's drone lookup. The existing roster
  and recon gating provide these behaviours consistently.
- Broad debug prints and historical ACTION_LOCKED message scanning were not
  restored; historical scanning can resend old commands.
- Mixed Pydantic/dictionary adapters are unnecessary with the branch's
  JSON-compatible mission state.
- The 118-line dependency freeze contains unrelated packages such as PyTorch,
  transformers, and desktop-input tools. These were not added as app dependencies.
- No local virtual environment, node_modules, generated world files, secrets,
  or simulator view settings were copied.

## Verification

Automated tests cover the imported target/waypoint behaviour, missing targets,
patrol failure propagation, both patrol parameter names, and matching clearance
between planner and controller. They run alongside the branch's LangGraph,
Socket.IO, mission lifecycle, and executor tests.

The earlier real-Webots test produced no controller telemetry. These source
changes and automated tests do not establish a successful live simulation.
