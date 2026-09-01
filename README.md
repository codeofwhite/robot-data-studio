# RoboData Studio

Local-first, engine-neutral simulation data collection platform. Genesis/ClothTwin
and Isaac Sim/Isaac Lab are the first engine plugins. The Studio owns sessions,
worker lifecycle, a common Episode contract and indexing; each engine retains its
native simulation, rendering and safety implementation.

## Start locally

Backend (terminal 1):

```bash
cd /data/zhanghejun/robot-data-studio
cp .env.example .env
set -a
source .env
set +a
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

The worker launcher builds argv arrays, never shell command strings. Genesis uses
its dedicated interpreter and `CUDA_VISIBLE_DEVICES`; Isaac Sim uses the Isaac Lab
launcher with `--gpu-id` and removes inherited `CUDA_VISIBLE_DEVICES`. Existing
ClothTwin manifests and the engine-neutral `robot_data_studio_episode` format are
both validated before indexing. Raw manifests are not rewritten by QA.

The checked-in `lab_d435i_dual_v1` Sensor Profile selects the active laboratory
D435i pair: `261722075807` for `agentview` and `261622075579` for `wrist`.
The historical `261622078553` unit is retained as inactive inventory and is not
launched by the platform profile. Its RGB intrinsics are intentionally null
until they are extracted from the physical cameras, so episodes are labeled
`nominal_pending_intrinsics` instead of calibrated.

The Isaac P0 scene records synchronized base and wrist RGB cameras, Franka joint/finger state,
applied joint targets, simulation time, and GELLO sequence/source timestamps.
Because `franka_empty` has no task evaluator, its automatic outcome is explicitly
`unavailable`; operator success/failure remains independent.

## Verification

```bash
cd /data/zhanghejun/robot-data-studio/backend
.venv/bin/python -m pytest -q

cd /data/zhanghejun/robot-data-studio
npm run build
```

Hardware/Genesis execution depends on the interpreter selected by `ROBOT_DATA_STUDIO_COLLECTOR_PYTHON`. The Studio backend environment intentionally does not duplicate the Genesis environment.

Current dependency preflight on this machine: the `genesis` environment can run collection but does not contain LeRobot or TensorFlow Datasets; `softmimicgen` contains `h5py` for Robomimic. The UI exposes all three standard formats now, but LeRobot/RLDS jobs will fail with an explicit log until their dedicated interpreter variables point to environments containing those exporters. No packages are installed implicitly by Studio.
