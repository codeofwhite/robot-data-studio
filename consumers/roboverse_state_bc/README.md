# RoboVerse PickCube state BC

This consumer trains a small action-chunk MLP from Studio-governed native
ManiSkill PickCube episodes. It deliberately reads the canonical Episode plus
its checksummed native payload instead of treating an export as an independent
source of truth.

## Evidence boundary

- Training accepts only Studio `qa_status=accepted` episodes with a successful
  native PickCube evaluator and complete `maniskill_source_episode_seed`
  provenance.
- The observation is 28-D: Panda qpos (9), qvel (9), cube pose (7), and goal
  position (3).
- The target is an 8-step chunk of 8-D normalized `pd_joint_delta_pos` actions.
  Official demonstrations contain values outside `[-1, 1]`; ManiSkill clips
  them before scaling, so this loader applies the same effective clipping and
  reports the raw out-of-bounds rate.
- Native payload schema `roboverse_maniskill_native_v2_pre_action` stores Panda,
  object, and task state immediately before every action. The loader forms exact
  `pre_action_state[t] -> action[t]` pairs and rejects legacy post-action-only
  payloads instead of silently shifting them.
- Train/validation splitting happens at Episode level before frame samples are
  created. The normalizer is fit on training episodes only.
- Policy and zero-action evaluation use native `gym.make("PickCube-v1")`, fresh
  `reset(seed)` state, and no action replay. The separate official-demo ceiling
  restores recorded initial state and is labeled as a non-distribution-matched
  replay ceiling.

## Dataset plan

The original P2-B run used 20 legacy post-action Episodes and remains preserved
as historical evidence. It completed the pipeline but scored 0/20 in native
closed loop. Those Episodes are not silently reused by the corrected loader.
New training data must carry the v2 pre-action schema. A fixed split seed
(`20260916`) produces 15 training and 5 validation episodes, while a separate
20-seed set is required for evaluation.

## Tests

```bash
cd /data/zhanghejun/robot-data-studio
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m unittest discover -s consumers/roboverse_state_bc -t . -p 'test_*.py' -v
```

## Train

Run only after all 20 source Episodes are QA accepted:

```bash
cd /data/zhanghejun/robot-data-studio
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m consumers.roboverse_state_bc.train \
  --dataset-name roboverse_p2b1_pickcube_v2 \
  --run-name pickcube_bc_v2
```

The run directory contains `checkpoint.pt`, `normalizer.npz`, `config.json`,
`split.json`, and `train_report.json`. Training refuses to reuse a non-empty run
directory.

## Single-Episode overfit gate

Before collecting a new 20-Episode dataset, collect and QA one v2 PickCube
Episode in dataset `roboverse_p2b1_pickcube_overfit`, then run:

```bash
cd /data/zhanghejun/robot-data-studio
CUDA_VISIBLE_DEVICES=7 \
MPLCONFIGDIR=/tmp/robot-data-studio-mpl \
XDG_CACHE_HOME=/tmp/robot-data-studio-cache \
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m consumers.roboverse_state_bc.overfit_one \
  --dataset-name roboverse_p2b1_pickcube_overfit \
  --sim-backend physx_cuda \
  --rollouts 3
```

This diagnostic deliberately restores the one training Episode's exact initial
state, but never replays an action. Targets with absolute action at least
`1 - 1e-6` are reported as saturated because the model's `tanh` output can only
approach them asymptotically. The gate passes only when teacher-forced MSE on
non-saturated action elements is at most `1e-6` and the learned policy succeeds
in all 3 native closed-loop runs. Overall and saturated MSE remain in the report.
The diagnostic proves state/action/control alignment, not held-out generalization.

## Native closed loop

Run this from a VSCode terminal with the intended GPU visible:

```bash
cd /data/zhanghejun/robot-data-studio
MPLCONFIGDIR=/tmp/robot-data-studio-mpl \
XDG_CACHE_HOME=/tmp/robot-data-studio-cache \
PYTHONPATH=. /data/zhanghejun/envs/roboverse-maniskill/bin/python \
  -m consumers.roboverse_state_bc.evaluate_maniskill \
  --checkpoint data/training/roboverse_state_bc/pickcube_bc_v1/checkpoint.pt \
  --sim-backend physx_cuda \
  --output data/evaluations/roboverse_state_bc/pickcube_bc_v1.json
```

The capability gate requires at least 10/20 policy successes, more successes
than zero-action on the paired seeds, and a one-sided exact paired p-value below
0.05. Otherwise the report is labeled
`training_and_closed_loop_pipeline_completed` rather than policy success.
