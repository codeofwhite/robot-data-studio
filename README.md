# RoboData Studio

Local-first, engine-neutral simulation data collection platform. Genesis/ClothTwin
and Isaac Sim/Isaac Lab are the first engine plugins. The Studio owns sessions,
worker lifecycle, a common Episode contract and indexing; each engine retains its
native simulation, rendering and safety implementation. The versioned schemas and
runtime-light writer/validator live in `packages/robot-data-contracts`; workers
depend on that package and never import Studio.

## Start locally

Backend (terminal 1):

```bash
cd /data/zhanghejun/robot-data-studio
cp .env.example .env
set -a
source .env
set +a
PYTHONPATH=packages/robot-data-contracts/src \
  backend/.venv/bin/python -m uvicorn robot_data_studio.main:app --app-dir backend/src --host 127.0.0.1 --port 8010 --reload
```

Frontend (terminal 2):

```bash
cd /data/zhanghejun/robot-data-studio
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
2. Confirm GPU, port, control frequency, and optional cloth parameters.
3. Start the allowlisted engine worker from the session page. Studio permits one managed simulator worker at a time.
4. Open the Collector. In GELLO mode, connect Web Serial there; Studio never proxies the control packets.
5. Save episodes through the engine console, then scan the session directory.
6. Mark QA accepted/rejected. Exports use only accepted episodes by default.

The worker launcher builds argv arrays, never shell command strings. Both
simulator workers are launched from `gello-remote`. Genesis uses its dedicated
interpreter, loads ClothTwin's scene implementation, and receives
`CUDA_VISIBLE_DEVICES`; Isaac Sim uses the Isaac Lab
launcher with `--gpu-id` and a one-device `CUDA_VISIBLE_DEVICES` mask. Isaac
routes RTX/Vulkan by the selected physical id and Isaac Lab/PhysX by the masked
logical `cuda:0`, so the worker does not create contexts on unselected GPUs. Existing
legacy ClothTwin manifests and the engine-neutral `robot_data_episode` v1 format
are both validated before indexing. Raw manifests are not rewritten by QA.

The checked-in `lab_d435i_dual_v1` Sensor Profile selects the active laboratory
D435i pair: `261722075807` for `agentview` and `261622075579` for `wrist`.
The historical `261622078553` unit is retained as inactive inventory and is not
launched by the platform profile. Its RGB intrinsics are intentionally null
until they are extracted from the physical cameras, so episodes are labeled
`nominal_pending_intrinsics` instead of calibrated.

Every v1 episode records native and policy state, operator/requested/safety-filtered/
actually-submitted actions, control/simulation/capture timestamps, camera calibration,
scene/asset/seed provenance, software revisions/dependencies, and evaluator version/metrics.
Because `franka_empty` has no task evaluator, its automatic outcome is explicitly
`unavailable`; operator success/failure remains independent.

## Verification

```bash
cd /data/zhanghejun/robot-data-studio
PYTHONPATH=backend/src:packages/robot-data-contracts/src \
  backend/.venv/bin/python -m pytest -q backend/tests packages/robot-data-contracts/tests

cd /data/zhanghejun/robot-data-studio
npm run build
```

Hardware/Genesis execution depends on the interpreter selected by `ROBOT_DATA_STUDIO_COLLECTOR_PYTHON`. The Studio backend environment intentionally does not duplicate the Genesis environment.

Current dependency preflight on this machine: the `genesis` environment can run collection but does not contain LeRobot or TensorFlow Datasets; `softmimicgen` contains `h5py` for Robomimic. Export and consumer interpreters are configured independently. No packages are installed implicitly by Studio.

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
The included seed-0 checkpoint is a one-episode pipeline sanity artifact: it is
interface-compatible with the worker safety layer, but it is not evidence of task
robustness or generalization.

Closed-loop validation is a separate two-process evaluation. The OpenPI environment
serves the custom checkpoint, while the Genesis environment runs the simulation-only
worker from `gello-remote`. The worker replans from current base/wrist images and
joint state, applies every predicted command through the scene's joint-limit and
slew-rate safety layer, and records an EpisodeContract trajectory plus four videos.
An episode passes only after grasp closure, a later release, the native task
evaluator, and ten stable target frames all pass; offline inference alone never sets
`closed_loop_validated=true`.
