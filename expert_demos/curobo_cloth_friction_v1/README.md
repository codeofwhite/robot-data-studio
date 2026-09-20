# Cloth friction contact v1

Independent copy of the assisted cuRobo cloth implementation. Source scenes,
task goals, robot geometry, force limits and health limits are inherited. Cloth
SoftPositionConstraint registration and animator were removed from this copy;
calling `attach_cloth_patch` raises an error. No cloth position setter runs after
initialization. Existing assisted data are reference data, not friction successes.

## Evidence boundary

This is synthetic Genesis FEM + IPC contact, with a full articulated Franka and
cuRobo collision-checked motion. Material constants are not measured fabric
parameters. The controller observes privileged simulated cloth geometry, not an
RGB perception policy. Actuator effort is a motor command, not a measured normal
contact force. Inner-pad proximity is a geometric diagnostic. A complete task
needs independent task evaluation and recorded-state visual review.

Status: **first task matrix completed / SELF_REVIEWED_PROVISIONAL**.
Read the [experiment report](../../data/expert_demos/curobo-cloth-friction-v1/REPORT.md)
for the saved results and evidence links.

Across 13 task types, 14 variants were attempted: one complete verified success
(`unfold_corner/v001`) and 13 failures. Twelve extra variants were not run after
their task's first failure. This is an adaptive engineering sweep, not a
statistical success-rate estimate. The failures comprise seven acquisition
verification failures, five finger-speed safety stops and one planning failure.
The box-cover attempt achieved 75.4% top coverage after its first release,
but coverage later fell to 20% and the next acquisition failed; it is not a
successful complete task. The original goals and guards were not relaxed.

The 2 ms step sensitivity probe stopped during closing at 0.20624 m/s finger
speed, exceeding the unchanged 0.2 m/s limit. The 4 ms successes therefore do
not establish numerical convergence or robust physical grasping. Full-task
failures and this sensitivity failure are part of the delivered evidence.

## Changes

- `runner.py`: explicit GPU mask, 4 ms baseline / 2 ms numerical probe, no
  assistance, matched no-close probe and original-scene initialization.
- `launch.py`: isolated output/cache root and one explicitly selected GPU shared
  by physics and the existing cuRobo subprocess.
- `runtime/scene.py`: no soft cloth constraint or target animator; native cloth
  constraint flags checked at every physics step and saved at each snapshot.
  Contact model coefficients, friction enablement and link indices are audited.
- `contact_grasp.py`: observe material points, align the jaws with hanging cloth,
  approach using actual pad dimensions and support clearance, close, lift 15 mm,
  hold 0.6 s and release. Verify at least 8 mm material lift, at most 4 mm slip,
  pad proximity on both sides and a nonzero loaded jaw gap. The evaluator
  recomputes these observations from saved vertices, joints and link poses.
- `tabletop_v2/actions.py`, `folding_v3/actions.py`, `fixtures_v4/actions.py` and
  `l_table_task.py`: shared physical acquisition/release replaces attachment.
  A failed acquisition stops the task with recorded evidence.
- `evaluate.py` and the three task `metrics.py` files: original task thresholds
  remain; an attachment event cannot establish execution in this version.
- `tests/test_friction_grasp.py`: reject empty grasps, material slip, short holds,
  out-of-pad proximity, fabricated success events and native cloth constraints.

Contact evaluation v2.1 measures a continuous two-ring material patch against
the actual inner pad faces. The initial v2.0 point-only diagnostic rejected a
valid nearby face contact: the target vertex lay outside the pad while its
adjacent triangles were gripped. Both positive and negative recordings were
reevaluated with the same corrected algorithm and unchanged 1.5 mm threshold.
Original online event diagnostics and raw trajectories remain saved.

Grasp success can be harder on a flat supported sheet: the table may prevent
the fingers from reaching opposing cloth surfaces. Such a failure requires a
physically justified acquisition action; increasing friction alone is not a
solution. Support clearance and measured collision guards remain active.

## Environment and tests

No new packages are installed. Existing interpreters:

- Physics: `/data/zhanghejun/miniconda3/envs/genesis/bin/python`
- Planner: `/data/zhanghejun/SIMPLE/.venv/bin/python`
- Recorded-state RTX rendering: `/data/zhanghejun/isaacsim_6.0.1/python.sh`

```bash
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B -m unittest discover \
  -s /data/zhanghejun/robot-data-studio/expert_demos/curobo_cloth_friction_v1/tests \
  -p test_friction_grasp.py -v
```

The inherited tests for assisted configuration remain reference tests and are
not this version's acceptance suite. Inherited batch builders/publication tools
have not been migrated; use the explicit entrypoints below.

## Probe invocation

Choose an idle GPU immediately before launching. The new output must not exist.
The initial hover plan is checked against the original scene geometry and base
transform. Only its independently planned initial robot pose is reused.

```bash
CLOTH_GPU=5 python3 -B \
  /data/zhanghejun/robot-data-studio/expert_demos/curobo_cloth_friction_v1/launch.py runner.py \
  --scene ttv2_unfold_corner_v001 --task unfold_corner \
  --scene-hover-plan /data/zhanghejun/robot-data-studio/data/expert_demos/curobo-cloth-v1/tabletop_v2/tasks/unfold_corner/v001/runs/ttv2-unfold-corner-v001-20260918t025235/initialization_plan.json \
  --grasp-probe-only --physics-dt 0.004 \
  --output /data/zhanghejun/robot-data-studio/data/expert_demos/curobo-cloth-friction-v1/probes/NEW_POSITIVE
```

Run the same command with `--negative-no-close` and a fresh output for the
negative control. A crash before closing is an incomplete control. A completed
negative control is expected to fail physical grasp, not be marked a successful
task. `--gripper-friction` and `--table-friction` are separate synthetic probes;
actual combined IPC coefficients are in `contact_audit.json`. No success
threshold is adjusted between controls or numerical probes.

Evaluate with:

```bash
/data/zhanghejun/miniconda3/envs/genesis/bin/python -B \
  /data/zhanghejun/robot-data-studio/expert_demos/curobo_cloth_friction_v1/evaluate.py \
  /data/zhanghejun/robot-data-studio/data/expert_demos/curobo-cloth-friction-v1/probes/NEW_POSITIVE
```

Full task runs omit `--grasp-probe-only` and require `--foundation` pointing to
the verified matched-control gate. The output root contains `reference_tasks.json` with 26 successful
assisted references across 13 task types; this inventory is not a friction
success count. Failed foundation gates block full-task expansion.

The matrix entrypoint `runner.py --run-reference-matrix REFERENCE_JSON
--foundation FOUNDATION_JSON --gpus 1,3 --output NEW_BATCH_DIRECTORY` uses
explicit available GPUs, starts with unfolding/flattening, and preserves every
launch command and evaluation. A task's first failure stops its extra variants;
other task types continue. `report.json` distinguishes physical failures,
untested variants and physical passes awaiting visual review.

The first foundation pair uses the original `ttv2_unfold_corner_v001` scene:
14.426 mm minimum local lift, 0.6 s hold, 0.032 mm material slip and 12.896 mm
release drop. The open-jaw control shows -0.158 mm local height change. These
are one matched pair, not success rates or material calibration. Both complete
recorded-state videos were decoded and checked (144 / 130 frames).

## Artifacts

All experiment data and explicitly configured experiment caches are under:
`/data/zhanghejun/robot-data-studio/data/expert_demos/curobo-cloth-friction-v1/`.

Each run retains resolved configuration, source snapshots/hashes, original
scene binding, actual IPC contact audit, complete physics log, recorded cloth
vertices and robot poses, events, run summary and independent evaluation.
Probe success is never marked `expert_eligible`.

`runtime/source/assets` was a symlink in the original tree; the independent
copy contains its original asset files so the runtime does not depend on a
mutable link back to the assisted source. Robot and pad geometry are unchanged.
The shared installed renderer may report its own default internal cache path;
the experiment does not install or upgrade that runtime.

The output `REPORT.md` and `results_summary.json` distinguish simulation
successes with reviewed videos from physical passes still awaiting review.
`summarize_results.py` regenerates both from saved evaluations and verifies
their input hashes. Raw failed runs and skipped variants remain visible.
