# RoboData Studio

Local-first, engine-neutral simulation data collection platform. Genesis/ClothTwin,
Isaac Sim/Isaac Lab, and RoboVerse run as isolated engine workers. The Studio owns
sessions, worker lifecycle, a common Episode contract and indexing; each engine
retains its native simulation, rendering and safety implementation. The versioned
schemas and runtime-light writer/validator live in `packages/robot-data-contracts`;
workers depend on that package and never import Studio.

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

The PickCube demo is already cached in this checkout. Fetch the two additional
official datasets into the same cache before starting PushCube or StackCube:

```bash
/data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m mani_skill.utils.download_demo PushCube-v1 \
  -o /data/zhanghejun/robot-data-studio/data/cache/maniskill
/data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m mani_skill.utils.download_demo StackCube-v1 \
  -o /data/zhanghejun/robot-data-studio/data/cache/maniskill
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
  backend/.venv/bin/python -m pytest -q backend/tests

PYTHONPATH=packages/robot-data-contracts/src \
  /home/zhanghejun/miniconda3/envs/genesis/bin/python \
  -m pytest -q packages/robot-data-contracts/tests

PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m unittest discover -s consumers/roboverse_state_bc -t . -p 'test_*.py' -v

cd /data/zhanghejun/robot-data-studio
npm run lint
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
The default local smoke checkpoint is the existing seed-0, 16-episode,
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
