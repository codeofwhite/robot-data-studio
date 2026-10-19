# RoboData Studio

[English](README.md) | [简体中文](README.zh-CN.md)

Local-first, engine-neutral simulation data collection platform. Genesis/ClothTwin,
Isaac Sim/Isaac Lab, and RoboVerse run as isolated engine workers. The Studio owns
sessions, worker lifecycle, a common Episode contract and indexing; each engine
retains its native simulation, rendering and safety implementation. The versioned
schemas and runtime-light writer/validator live in `packages/robot-data-contracts`;
workers depend on that package and never import Studio.

**Looking for where to start?** See [`docs/START_HERE.md`](docs/START_HERE.md) — repo map, which door to open by intent, and what the evidence levels do and do not prove.

## Capabilities and requirements

| Area | What the repository provides | Additional requirements |
| --- | --- | --- |
| Collection | Sessions, isolated workers, keyboard/GELLO entry points | A compatible engine runtime, worker checkout, and scene assets |
| Data review | Episode indexing and operator QA | Recorded canonical Episodes |
| Export and training integration | LeRobot/OpenPI views and consumer checks | The selected exporter, model, and training environment |
| Dual FR3 deployment | Pinned code and asset preparation | Separate Isaac SDK/environment installation and on-machine validation |

Use **Python 3.12+** for the backend and **Node.js 22.13+** for the frontend.
The Studio environment manages the UI and API; each simulator, exporter, and
policy can use its own environment. A fresh clone contains neither collected
Episodes nor model checkpoints, simulator SDKs, or downloaded asset libraries.

- [Repository map](docs/START_HERE.md)
- [Data-to-training workflow](docs/DATA_TO_TRAINING_GUIDE_ZH.md)
- [Dual FR3 / GELLO deployment](docs/franka5090_deployment.md)

### Install the UI and API dependencies

The following commands are installation instructions, not an automatic simulator
setup. Run them from the repository root in a new or intentionally selected environment:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e './packages/robot-data-contracts' -e './backend[dev]'
npm ci
```

Review `.env.example`, copy it to `.env` if you do not already have a local
configuration, and replace workspace paths for the engines you intend to use.
The example is sourced by the shell below; its `${...}` variables require shell
expansion. Starting the UI/API does not install or start a simulation worker.

## Start locally

Backend (terminal 1):

```bash
cd /absolute/path/to/robot-data-studio
test -f .env || cp .env.example .env
set -a
source .env
set +a
PYTHONPATH=packages/robot-data-contracts/src \
  backend/.venv/bin/python -m uvicorn robot_data_studio.main:app --app-dir backend/src --host 127.0.0.1 --port 8010 --reload
```

Frontend (terminal 2):

```bash
cd /absolute/path/to/robot-data-studio
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:3000`. API documentation is at `http://127.0.0.1:8010/docs`.
When working through VS Code/SSH, forward the fixed ports used by the platform:

- `3000` for the Studio frontend;
- `8010` for the Studio API;
- `8080` for the default Collector HTTP and WebSocket endpoint.

Keep the same local port numbers so the browser URLs remain
`http://127.0.0.1:3000`, `http://127.0.0.1:8010`, and
`http://127.0.0.1:8080` without additional configuration.

## Collection flow

1. Create a session and choose an engine, scene, control source, and Sensor Profile.
2. Confirm the applicable GPU, Collector port, control frequency, and optional scene parameters.
3. Start the allowlisted engine worker from the session page. Studio permits one managed simulator worker at a time.
4. For interactive Genesis/Isaac sessions, open the Collector. In GELLO mode, connect Web Serial there; Studio never proxies the control packets.
5. For a headless RoboVerse session, wait for the scripted batch to finish. It does not expose a Collector port.
6. Save interactive episodes or finish the headless batch, then scan the session directory.
7. Mark QA accepted/rejected. Exports use only accepted episodes by default.

The worker launcher builds argv arrays, never shell command strings. Genesis and
Isaac workers are launched from `gello-remote`. Genesis uses its dedicated
interpreter, loads ClothTwin's scene implementation, and receives
`CUDA_VISIBLE_DEVICES`; Isaac Sim uses the Isaac Lab
launcher with `--gpu-id` and a one-device `CUDA_VISIBLE_DEVICES` mask. Isaac
routes RTX/Vulkan by the selected physical id and Isaac Lab/PhysX by the masked
logical `cuda:0`, so the worker does not create contexts on unselected GPUs. Existing
legacy ClothTwin manifests and the engine-neutral `robot_data_episode` v1 format
are both validated before indexing. Raw manifests are not rewritten by QA.

### Isaac dual-Franka workstation and ClothForge garments

The v17 workstation reuses the existing USD table, dual Franka robots, materials,
and lighting. Choose one of these scenes under **Isaac Sim**:

| Scene ID | Content | Physics backend |
| --- | --- | --- |
| `bimanual_tabletop_v17` | Workstation with a rigid object | PhysX |
| `bimanual_tabletop_v17_cloth` | Workstation with the existing rectangular cloth USD | PhysX |
| `bimanual_tabletop_v17_clothforge` | Workstation with a selectable ClothForge garment | PhysX or Newton |

1. Create a session and select the desired v17 scene. The form defaults to
   **GELLO** and **PhysX**, with **960×720** cameras. An FR3 deployment selects
   `isaac_fr3_dual_wrist_v1`; otherwise the form selects
   `isaac_bimanual_tabletop_visual_v5`. Choose Keyboard explicitly when needed.
2. For ClothForge, select a registered garment and a `light`, `medium`, or `heavy`
   material preset. The form loads the garment's preset values; you can override
   area density, friction, stretch, area constraint, bending, scale, tabletop
   rotation, X/Y offset, and cloth solver iterations.
3. To use Newton, select it in **Physics Backend**. This garment route uses
   **MJWarp + VBD with two-way coupling** for robot–cloth contact. Other v17
   variants currently require PhysX.
4. Select the worker GPU, start the worker, and open the Collector. Give the
   keyboard control area focus and press **Tab** to switch the primary arm.
   Use the Collector's movement, gripper, recording, and reset controls.
5. Save and scan the Episode, then review it through the normal QA flow.

Garment parameters take effect at worker startup. Start a new session or restart
with updated session parameters to apply changes. Garment selection uses the
Studio Asset Registry; the worker loads the corresponding ClothForge source
mesh and material configuration without rewriting the original asset. The
ClothForge source root is configured by `ROBOT_DATA_STUDIO_CLOTHFORGE_ROOT`
(set it to your ClothForge checkout). This route runs in the existing
Isaac Lab worker environment and requires its Newton integration when Newton
is selected; the backend Python environment alone does not provide simulation.

PhysX converts ClothForge material values to its deformable-material model;
Newton uses the native cloth coefficients, planar pattern rest metric, and seam
information. Matching input presets does not establish physical equivalence
between the two solvers. Episodes retain the garment, material parameters, and
physics configuration for inspection.

The local Newton T-shirt smoke on 2026-10-10 verified startup, tabletop contact,
control of both arms and grippers, reset, and a 167-frame recording with finite
state values. With 12 cloth iterations, measured control rate was about 10–11 Hz;
this is a configuration-specific result. Stable grasp/lift and garment task
success remain unverified. See the local
`data/verification/clothforge_newton_v17_20261010/verification_summary.json`
for evidence; verification artifacts are not included in a fresh checkout.

### RoboVerse ManiSkill batch

The RoboVerse worker runs PickCube, PushCube, or StackCube as an isolated
headless scripted batch. A session generates 1 to 10 episodes at a fixed 20 Hz
using official ManiSkill Panda `pd_joint_delta_pos` demonstrations. The task
descriptor selects the demo H5/JSON files, native task, 50-step horizon, actor
mapping, task-state schema, and evaluator. `episode_steps` may shorten a replay
for failure-path testing, while `demo_offset` selects a different consecutive
window of successful source trajectories.

Each saved Episode records the official demonstration trajectory, its original
`episode_seed` from ManiSkill metadata, hashes for both source files, and
task-level evaluator metrics. Restoring the full demonstration state preserves
the original randomized initial condition; Studio does not relabel a locally
incremented counter as a new task seed. PickCube diagnoses grasp/goal/static
failures, PushCube diagnoses goal/surface failures, and StackCube diagnoses
grasp/alignment/release/stability failures.

GPU selection remains meaningful because the worker receives
`CUDA_VISIBLE_DEVICES`, but it has no Collector port and does not support GELLO
or keyboard control. When the process completes, scan the session and use the
same Studio QA, accepted-only export, and consumer-smoke flow as other engines.

Download the official demonstrations required by your tasks into the configured
cache; an existing local cache is not part of a fresh clone. For example:

```bash
"${ROBOT_DATA_STUDIO_ROBOVERSE_PYTHON}" \
  -m mani_skill.utils.download_demo PushCube-v1 \
  -o "${ROBOT_DATA_STUDIO_ROBOVERSE_DEMO_ROOT}"
"${ROBOT_DATA_STUDIO_ROBOVERSE_PYTHON}" \
  -m mani_skill.utils.download_demo StackCube-v1 \
  -o "${ROBOT_DATA_STUDIO_ROBOVERSE_DEMO_ROOT}"
```

### PickCube state-BC consumer

`consumers/roboverse_state_bc` provides the first small-policy path for
RoboVerse data. It loads only Studio QA-accepted PickCube Episodes with complete
P2 seed provenance, uses the checksummed native Panda state/task state/action
payload, performs an Episode-level 15/5 split, and saves a checkpoint,
training-only normalizer, configuration, split UUIDs/seeds, Git state, and a
training report. It does not train from rejected Episodes or split frames from
one Episode across train and validation. Native payload schema
`roboverse_maniskill_native_v2_pre_action` records state immediately before
each action and gives the loader exact `state[t] -> action[t]` pairs. The loader
explicitly rejects legacy post-action-only payloads; historical raw Episodes
and their P2-B 0/20 evaluation remain immutable evidence.

The learned policy is evaluated directly in native `PickCube-v1` from fresh
`reset(seed)` states. It receives Panda qpos/qvel, cube pose, and goal position,
then emits bounded 8-D `pd_joint_delta_pos` action chunks. The policy path does
not restore demonstration state or replay demonstration actions. Zero action is
run on the same 20 held-out seeds. An official-demo replay ceiling is also
reported, but it restores the recorded initial state and is explicitly not
treated as a distribution-matched policy baseline. See
[`consumers/roboverse_state_bc/README.md`](consumers/roboverse_state_bc/README.md)
for commands and evidence gates.

The single-Episode alignment diagnostic uses a separate gate: non-saturated
teacher-forced action MSE at most `1e-6` plus 3/3 native closed-loop successes
from the restored training initial state. Saturated, non-saturated, and overall
MSE are all retained in its report. This is an alignment check and does not
replace the 20-seed held-out capability gate.

## Worker runtime reliability

Studio launches each engine through a durable supervisor. Every launch receives a
run UUID and records the supervisor/child PIDs, Linux boot ID and process start
identity, readiness, heartbeat, exit status, log path, and resource locks in
SQLite. Genesis and Isaac become ready only after their control TCP endpoint is
listening; RoboVerse writes a run-specific ready marker after native task
initialization. Restarting the Studio API reconciles these durable records instead
of relying on an in-memory `subprocess.Popen` object.

Studio-managed workers atomically lock the global simulator slot, selected GPU,
Collector/signaling/media ports where applicable, and the session output root.
An exited worker releases its locks but keeps the immutable run record for audit.
`failed` means the supervised process reported a launch/runtime failure;
`orphaned` means the persisted PID identity is absent or no longer matches, so
Studio refuses to signal that PID.

Sensor profiles describe configured camera roles and mounts. Physical-device
serial numbers and per-device calibration belong to local configuration. A profile
with missing intrinsics remains `nominal_pending_intrinsics`; select and calibrate
your own devices before claiming a match to a physical camera setup. Existing
profile files have not been migrated by this documentation update.

Every v1 episode records native and policy state, operator/requested/safety-filtered/
actually-submitted actions, control/simulation/capture timestamps, camera calibration,
scene/asset/seed provenance, software revisions/dependencies, and evaluator version/metrics.
Because `franka_empty` has no task evaluator, its automatic outcome is explicitly
`unavailable`; operator success/failure remains independent.

## Verification

Run these checks in environments with their test dependencies installed. Load
`.env` in this terminal before using the configured engine interpreters. The
commands are verification entry points, not a claim that every engine has been
validated on a new machine.

```bash
cd /absolute/path/to/robot-data-studio
PYTHONPATH=backend/src:packages/robot-data-contracts/src \
  backend/.venv/bin/python -m pytest -q backend/tests

PYTHONPATH=packages/robot-data-contracts/src \
  "${ROBOT_DATA_STUDIO_COLLECTOR_PYTHON}" \
  -m pytest -q packages/robot-data-contracts/tests

PYTHONPATH=. "${ROBOT_DATA_STUDIO_ROBOVERSE_PYTHON}" \
  -m unittest discover -s consumers/roboverse_state_bc -t . -p 'test_*.py' -v

cd /absolute/path/to/robot-data-studio
npm run lint
npm run build
```

Hardware/Genesis execution depends on the interpreter selected by `ROBOT_DATA_STUDIO_COLLECTOR_PYTHON`. The Studio backend environment intentionally does not duplicate the Genesis environment.

A previous development-machine dependency snapshot (not a fresh-clone guarantee): the `genesis` environment can run collection but does not contain LeRobot or TensorFlow Datasets; `softmimicgen` contains `h5py` for Robomimic. Export and consumer interpreters are configured independently. No packages are installed implicitly by Studio.

The export UI distinguishes current LeRobot v3 from OpenPI's vendored LeRobot
v2.1. Current v3 accepts `physical_joint8` and `fastwam_franka_joint8`; v2.1
requires `openpi_franka_joint8`. These are explicit export-time views and never
overwrite the raw episode. The FastWAM view uses 8-D proprio/action with a 32-step
action horizon. The OpenPI view stores absolute 7-joint targets plus an absolute
closed-fraction gripper channel; its consumer transform converts the seven joint
channels to deltas and pads the model tensors to 32 dimensions.

Successful OpenPI v2.1 and FastWAM v3 exports automatically launch a consumer
smoke. Export and smoke status are independent. Each smoke decodes actual images,
loads the task instruction, assembles one state/action batch through the real
consumer loader and processor, and writes a JSON report below
`<export>/consumer_smoke/`. A completed export with a failed smoke is not considered
training-ready.

The OpenPI smoke additionally loads the configured checkpoint and runs one real
JAX policy forward on a single explicitly selected GPU. The
`pi05_franka_joint8_lora` integration computes dataset-specific normalization,
trains on seven joint deltas plus an absolute gripper channel, and converts policy
outputs back to 8-D absolute Franka joint targets. The report records model
execution, action-contract compatibility, and closed-loop validation separately.
A previous development smoke used a seed-0, 16-episode,
2,000-step Franka joint8 artifact. It is interface-compatible with the worker
safety layer, but it is not evidence of Isaac task robustness or generalization.

Closed-loop validation is a separate two-process evaluation. The OpenPI environment
serves the custom checkpoint, while the Genesis environment runs the simulation-only
worker from `gello-remote`. The worker replans from current base/wrist images and
joint state, applies every predicted command through the scene's joint-limit and
slew-rate safety layer, and records an EpisodeContract trajectory plus four videos.
An episode passes only after grasp closure, a later release, the native task
evaluator, and ten stable target frames all pass; offline inference alone never sets
`closed_loop_validated=true`.

For the fixed Isaac Sim cube-lift collection, QA, OpenPI export, pilot-check, and
short-overfit sequence, follow [`docs/ISAAC_CUBE_OPENPI_PILOT.md`](docs/ISAAC_CUBE_OPENPI_PILOT.md).
