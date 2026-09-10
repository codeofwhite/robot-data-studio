# Isaac cube-lift to OpenPI pilot

This pilot answers one question only: can canonical episodes collected by the
Isaac Sim worker train the existing Franka joint8 OpenPI policy bridge? Keep the
scene, cameras, lighting, robot home, cube pose, prompt, dataset FPS, and seed
fixed until the 20-episode overfit gate passes.

## 1. Collect in three gates

Create a Studio session with:

- Dataset: `isaac_cube_lift_pilot`
- Simulator: `Isaac Sim`
- Scene: `刚体方块抓取抬升 (rigid_cube_lift)`
- Control: keyboard for an interface smoke, then GELLO for demonstrations
- Sensor profile: `lab_d435i_dual_v1`
- Dataset FPS: 10 Hz
- Seed: 0
- Work surface height: 0.25 m

For every episode, perform one clean sequence:

1. approach with the gripper open;
2. close on the green cube;
3. lift at least 8 cm;
4. hold above the threshold for at least one second;
5. release, then leave several post-release frames.

Use three gates instead of collecting 20 episodes immediately:

1. Save one episode and scan it in Studio. Confirm four moving RGB streams,
   finite 8-D policy state/action, `engine_id=isaac_sim`, `scene_id=rigid_cube_lift`,
   and evaluator success.
2. Collect three episodes. Reject any collision, missed grasp, stale image,
   operator/automatic outcome disagreement, or incorrect open-close-open action.
3. Collect and accept exactly 20 clean episodes only after gates 1 and 2 pass.

The OpenPI adapter consumes `base+wrist`. `top` and `side` remain recorded for
QA and provenance in this P0 experiment; changing the policy image mapping is a
separate experiment.

## 2. Export and validate

In Studio, filter Episodes by `Isaac Sim`, accept only the 20 valid cube-lift
episodes, then export them as `OpenPI LeRobot v2.1` with profile
`openpi_franka_joint8`. Do not mix Genesis episodes into this pilot.

Run the dataset gate in the OpenPI environment, replacing the export path:

```bash
cd /data/zhanghejun/robot-data-studio
PILOT_EXPORT=/absolute/path/to/the/openpi_v21_export
PYTHONPATH=/data/zhanghejun/robot-data-studio:/data/zhanghejun/openpi/src \
  /data/zhanghejun/openpi/.venv/bin/python \
  -m consumers.openpi_franka_joint8.pilot_check \
  --dataset-root "$PILOT_EXPORT" \
  --expected-episodes 20 \
  --report data/training/isaac_cube_lift_seed0/reports/pilot_check.json
```

Do not train unless this report says `status: passed`.

## 3. Norm stats, batch preflight, and short overfit

Use the cached pi0.5 base checkpoint and a new training root so this run cannot
overwrite the prior Genesis result:

```bash
cd /data/zhanghejun/robot-data-studio
PILOT_EXPORT=/absolute/path/to/the/openpi_v21_export
PILOT_TRAINING=/data/zhanghejun/robot-data-studio/data/training/isaac_cube_lift_seed0
PI05_BASE=/home/zhanghejun/.cache/openpi/openpi-assets/checkpoints/pi05_libero
PILOT_PYTHON=/data/zhanghejun/openpi/.venv/bin/python
PILOT_PYTHONPATH=/data/zhanghejun/robot-data-studio:/data/zhanghejun/openpi/src:/data/zhanghejun/openpi/packages/openpi-client/src

CUDA_VISIBLE_DEVICES=7 PYTHONPATH="$PILOT_PYTHONPATH" "$PILOT_PYTHON" \
  -m consumers.openpi_franka_joint8.run stats \
  --dataset-root "$PILOT_EXPORT" --training-root "$PILOT_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --report "$PILOT_TRAINING/reports/norm_stats.json"

CUDA_VISIBLE_DEVICES=7 PYTHONPATH="$PILOT_PYTHONPATH" "$PILOT_PYTHON" \
  -m consumers.openpi_franka_joint8.run preflight \
  --dataset-root "$PILOT_EXPORT" --training-root "$PILOT_TRAINING" \
  --base-checkpoint "$PI05_BASE" \
  --report "$PILOT_TRAINING/reports/preflight.json"

CUDA_VISIBLE_DEVICES=7 PYTHONPATH="$PILOT_PYTHONPATH" "$PILOT_PYTHON" \
  -m consumers.openpi_franka_joint8.run train \
  --dataset-root "$PILOT_EXPORT" --training-root "$PILOT_TRAINING" \
  --base-checkpoint "$PI05_BASE" --experiment-name isaac_cube_lift_overfit20_seed0 \
  --num-train-steps 500 --report "$PILOT_TRAINING/reports/train_step500.json"
```

Start with 500 steps. Continue to 2,000 only if loss is finite and decreasing
but the gripper phase gate has not yet passed. Keep seed 0 and do not add scene
randomization during this stage.

Evaluate the 500-step checkpoint on the same 20 episodes as an explicit overfit
test (not a held-out result):

```bash
PILOT_CHECKPOINT="$PILOT_TRAINING/checkpoints/pi05_franka_joint8_lora/isaac_cube_lift_overfit20_seed0/499"
CUDA_VISIBLE_DEVICES=7 PYTHONPATH="$PILOT_PYTHONPATH" "$PILOT_PYTHON" \
  -m consumers.openpi_franka_joint8.evaluate_val \
  --dataset-root "$PILOT_EXPORT" --training-root "$PILOT_TRAINING" \
  --base-checkpoint "$PI05_BASE" --checkpoint "$PILOT_CHECKPOINT" \
  --experiment-name isaac_cube_lift_overfit20_seed0 --num-train-steps 500 \
  --report "$PILOT_TRAINING/reports/overfit_phase_step499.json"
```

## 4. Evidence and stop conditions

The first result is an offline overfit result, not closed-loop task success.
Check phase-labelled validation with `evaluate_val.py`, including joint MAE,
close recall, open specificity, and separate approach/close/transport/release
windows. Then run at least 20 policy rollouts in Isaac and report grasp, lift,
hold, and release rates separately.

For event-aware training, pass `--sampling-strategy phase_balanced`. The local
consumer labels each episode into approach-open, close-transition,
closed-transport, release-transition, and post-release frames, then samples
them with target probabilities `25/20/25/20/10%`. Normalization statistics are
still computed from the unweighted dataset. Treat this as phase-weighted
sampling, not as a modification of OpenPI's model loss.

The Isaac worker now supports `--control-source openpi` with the same websocket
contract as the Genesis rollout worker. It resets and runs multiple
`rigid_cube_lift` episodes in one Kit process, records requested/safe/applied
actions, and saves base/top/side/wrist MP4 files plus parseable per-rollout and
batch reports.

Stop and debug the data/contract before scaling if any of these occurs:

- pilot check fails provenance, camera, shape, finite-value, or action-phase gates;
- OpenPI consumer smoke cannot decode real images and one real batch;
- normalization statistics contain non-finite or near-constant action channels;
- training loss does not decrease on the fixed 20-episode set;
- the gripper predicts only open or only closed;
- offline phase metrics pass but the cube never lifts in closed loop.

## 5. M5c gripper-event-aware diagnostic

M5c keeps the seven arm-action dimensions unchanged and compares four gripper
timing variants on the same 42 successful M2 demonstrations and the same 252
teacher-forced event frames. The variants are the existing horizon-10 baseline,
a horizon-4 policy, a horizon-10 policy with asymmetric close-boundary sampling,
and a frozen baseline arm policy with an independent binary gripper head.

The promotion gate requires both approach-open specificities to be at least
0.8, close recall at least 0.8, grasp and lift close recall at least 0.95,
joint first-step MAE at most 0.1 rad, median chunk close offset within one frame,
and exact preservation of the seven arm outputs for the independent head.
No variant passed every gate, so M5c intentionally performed no new Isaac
physics rollouts.

| Variant | Joint MAE (rad) | Open spec. -5 / -2 | Close / grasp / lift recall | Median close offset | Gate |
|---|---:|---:|---:|---:|---|
| Baseline H10 | 0.00424 | 0.238 / 0.167 | 0.929 / 1.000 / 1.000 | -2 frames | FAIL |
| Short H4 | 0.00416 | 0.310 / 0.143 | 0.929 / 0.976 / 1.000 | 0 frames | FAIL |
| Event H10 | 0.00459 | 0.643 / 0.452 | 0.667 / 0.929 / 1.000 | 0 frames | FAIL |
| Binary head H10 | 0.00424 | 0.500 / 0.476 | 0.810 / 1.000 / 0.738 | -1 frame | FAIL |

The result separates chunk alignment from event classification. Short horizon
fixes the median chunk offset but not the first-step premature-close error.
Asymmetric sampling improves approach-open specificity but suppresses the true
close event. The 200-step CPU binary-head sanity run improves the baseline's
approach-open specificity and exactly preserves the arm output, but it still
closes early and fails to keep the gripper closed through lift. These are
teacher-forced diagnostics, not task-success evidence.
