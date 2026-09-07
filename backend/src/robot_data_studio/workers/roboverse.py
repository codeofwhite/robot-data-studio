from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import signal
import sys
from pathlib import Path
from typing import Any

import numpy as np

from robot_data_contracts import (
    AugmentationLineageV1,
    EpisodeWriter,
    EvaluatorResultV1,
    SceneProvenanceV1,
)
from robot_data_contracts.profiles.franka import (
    FRANKA_JOINT8_ACTION,
    franka_feature_specs,
    policy_action_from_native,
    policy_state_from_native,
)
from robot_data_contracts.provenance import collect_software_provenance


ARM_JOINTS = tuple(f"panda_joint{index}" for index in range(1, 8))
FINGER_JOINTS = ("panda_finger_joint1", "panda_finger_joint2")
NATIVE_JOINTS = ARM_JOINTS + FINGER_JOINTS
ROBOVERSE_TASKS = {
    "maniskill_pick_cube_native": "maniskill.pick_cube_native",
}
CAMERA_POSITION = (1.1, -1.1, 0.9)
CAMERA_LOOK_AT = (-0.1, 0.0, 0.15)
CAMERA_VERTICAL_FOV_DEG = 42.0
CAMERA_FOCAL_LENGTH = 24.0


def _as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _named_values(names: list[str], values: Any, expected: tuple[str, ...]) -> np.ndarray:
    flat = _as_numpy(values).reshape(-1)
    if len(names) != len(flat):
        raise ValueError(f"joint name/value mismatch: {len(names)} names for {len(flat)} values")
    by_name = dict(zip(names, flat, strict=True))
    missing = [name for name in expected if name not in by_name]
    if missing:
        raise ValueError(f"RoboVerse Panda state is missing joints: {missing}")
    return np.asarray([by_name[name] for name in expected], dtype=np.float32)


def extract_native_state(task: Any) -> np.ndarray:
    robot = task.handler.object_ids["panda"]
    active_names = [joint.get_name() for joint in robot.get_active_joints()]
    qpos = _named_values(active_names, robot.get_qpos(), NATIVE_JOINTS)
    qvel = _named_values(active_names, robot.get_qvel(), NATIVE_JOINTS)
    return np.concatenate([qpos, qvel]).astype(np.float32)


def absolute_native_target(task: Any, normalized_action: Any) -> np.ndarray:
    target = _as_numpy(task._targets_from_action(normalized_action)).reshape(-1)
    sorted_names = list(task.handler.get_joint_names("panda", sort=True))
    return _named_values(sorted_names, target, NATIVE_JOINTS)


def scripted_action(step: int, total_steps: int) -> np.ndarray:
    phase = 2.0 * math.pi * step / max(total_steps, 1)
    action = np.zeros(8, dtype=np.float32)
    action[0] = 0.04 * math.sin(phase)
    action[1] = 0.025 * math.sin(phase * 0.5)
    action[6] = 0.03 * math.cos(phase)
    action[7] = 0.4
    return action


def _camera_geometry(width: int, height: int) -> tuple[float, list[list[float]]]:
    horizontal_aperture = (
        2.0
        * CAMERA_FOCAL_LENGTH
        * math.tan(math.radians(CAMERA_VERTICAL_FOV_DEG) / 2.0)
        * width
        / height
    )
    focal_pixels = width * CAMERA_FOCAL_LENGTH / horizontal_aperture
    return horizontal_aperture, [
        [focal_pixels, 0.0, width / 2.0],
        [0.0, focal_pixels, height / 2.0],
        [0.0, 0.0, 1.0],
    ]


def _camera_image(observation: Any) -> np.ndarray:
    try:
        rgb = observation.cameras["base"].rgb
    except (AttributeError, KeyError) as error:
        raise RuntimeError("RoboVerse SAPIEN3 observation is missing base RGB") from error
    image = _as_numpy(rgb)
    if image.ndim == 4:
        image = image[0]
    if image.dtype != np.uint8:
        if np.issubdtype(image.dtype, np.floating) and image.max(initial=0) <= 1.0:
            image = image * 255.0
        image = np.clip(image, 0, 255).astype(np.uint8)
    return image[..., :3]


def _object_observation(task: Any) -> tuple[np.ndarray, np.ndarray]:
    pose = np.concatenate([task.obj_pos("cube"), task.obj_quat("cube")]).astype(np.float32)
    velocity = np.concatenate([task.obj_linvel("cube"), task.obj_angvel("cube")]).astype(np.float32)
    return pose, velocity


def _asset_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_native_payload(path: Path, arrays: dict[str, list[np.ndarray]]) -> None:
    payload_path = path / "native_trajectory.npz"
    np.savez_compressed(
        payload_path,
        **{name: np.stack(values) for name, values in arrays.items()},
    )
    digest = _asset_sha256(payload_path)
    (path / "native_payload.sha256").write_text(
        f"{digest}  native_trajectory.npz\n", encoding="utf-8"
    )


def _build_task(width: int, height: int):
    import roboverse_pack.tasks.maniskill  # noqa: F401
    from metasim.scenario.cameras import PinholeCameraCfg
    from metasim.task.registry import get_task_class

    task_class = get_task_class(ROBOVERSE_TASKS["maniskill_pick_cube_native"])
    scenario = copy.deepcopy(task_class.scenario)
    scenario.simulator = "sapien3"
    scenario.num_envs = 1
    scenario.headless = True
    horizontal_aperture, _ = _camera_geometry(width, height)
    scenario.cameras = [
        PinholeCameraCfg(
            name="base",
            data_types=["rgb"],
            width=width,
            height=height,
            pos=CAMERA_POSITION,
            look_at=CAMERA_LOOK_AT,
            focal_length=CAMERA_FOCAL_LENGTH,
            horizontal_aperture=horizontal_aperture,
        )
    ]
    return task_class(scenario)


def _software_provenance() -> Any:
    return collect_software_provenance(
        engine_id="roboverse_sapien3",
        engine_version=importlib.metadata.version("sapien"),
        worker_id="roboverse_maniskill_worker",
        git_roots={"roboverse": Path.cwd()},
        packages=("roboverse-py", "sapien", "torch", "numpy"),
    )


def collect(args: argparse.Namespace) -> list[Path]:
    if args.scene not in ROBOVERSE_TASKS:
        raise ValueError(f"unsupported RoboVerse scene: {args.scene}")
    if not 1 <= args.episodes <= 10:
        raise ValueError("episodes must be between 1 and 10")
    if not 2 <= args.steps <= 50:
        raise ValueError("steps must be between 2 and 50")
    if args.fps != 20:
        raise ValueError("ManiSkill native collection requires fps=20")
    profile = json.loads(args.camera_profile_file.read_text(encoding="utf-8"))
    role = profile["roles"]["agentview"]
    _, intrinsics = _camera_geometry(args.width, args.height)
    camera_calibration = {
        "base": {
            "role": "agentview",
            "profile": profile["id"],
            "intrinsics": intrinsics,
            "extrinsics": {
                "position_world_m": list(CAMERA_POSITION),
                "lookat_world_m": list(CAMERA_LOOK_AT),
                "convention": "sapien_x_forward_z_up",
            },
            "model": role["model"],
        }
    }
    software = _software_provenance()
    task = _build_task(args.width, args.height)
    saved: list[Path] = []
    stop_requested = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    try:
        for episode_offset in range(args.episodes):
            if stop_requested:
                break
            episode_seed = args.seed + episode_offset
            observation, _ = task.reset(seed=episode_seed)
            writer = EpisodeWriter(
                args.data_dir,
                fps=args.fps,
                robot_id="franka_panda",
                control_source="scripted_roboverse_probe",
                features=franka_feature_specs(
                    tuple(f"normalized_pd_joint_delta/{index}" for index in range(8))
                ),
                action_profile=FRANKA_JOINT8_ACTION,
                camera_names=("base",),
                camera_calibration=camera_calibration,
                scene=SceneProvenanceV1(
                    scene_id=args.scene,
                    seed=episode_seed,
                    parameters={
                        "upstream_task": ROBOVERSE_TASKS[args.scene],
                        "simulator": "sapien3",
                        "control_policy": "deterministic_scripted_probe_v1",
                        "episode_steps": args.steps,
                        "safety_filter": "identity_simulation_only",
                        "camera_profile_id": profile["id"],
                    },
                    assets=[
                        {
                            "role": "native_payload",
                            "path": "native_trajectory.npz",
                            "checksum": "native_payload.sha256",
                        }
                    ],
                ),
                software=software,
                lineage=AugmentationLineageV1(generation_method="scripted"),
            )
            native_arrays: dict[str, list[np.ndarray]] = {
                "normalized_action": [],
                "absolute_joint_target": [],
                "joint_state": [],
                "cube_pose": [],
                "cube_velocity": [],
            }
            writer.start(ROBOVERSE_TASKS[args.scene])
            succeeded = False
            last_reward = 0.0
            try:
                for step in range(args.steps):
                    if stop_requested:
                        raise InterruptedError("worker stop requested")
                    normalized = scripted_action(step, args.steps)
                    absolute_target = absolute_native_target(task, normalized)
                    observation, reward, terminated, timeout, _ = task.step(normalized[None, :])
                    state = extract_native_state(task)
                    object_pose, object_velocity = _object_observation(task)
                    succeeded = succeeded or bool(_as_numpy(terminated).reshape(-1)[0])
                    last_reward = float(_as_numpy(reward).reshape(-1)[0])
                    writer.add_frame(
                        images={"base": _camera_image(observation)},
                        values={
                            "native_state": state,
                            "policy_state": policy_state_from_native(state),
                            "operator_action": normalized,
                            "requested_action": policy_action_from_native(absolute_target),
                            "safe_action": policy_action_from_native(absolute_target),
                            "applied_action": policy_action_from_native(absolute_target),
                            "object_pose": object_pose,
                            "object_velocity": object_velocity,
                        },
                        simulation_time_s=(step + 1) / args.fps,
                        control_sequence=step,
                    )
                    for name, value in (
                        ("normalized_action", normalized),
                        ("absolute_joint_target", absolute_target),
                        ("joint_state", state),
                        ("cube_pose", object_pose),
                        ("cube_velocity", object_velocity),
                    ):
                        native_arrays[name].append(np.asarray(value))
                    if bool(_as_numpy(timeout).reshape(-1)[0]):
                        break
                evaluator = EvaluatorResultV1(
                    evaluator_id="roboverse_maniskill_success",
                    evaluator_version="native_v1",
                    available=True,
                    success=succeeded,
                    metrics={"last_dense_reward": last_reward, "scripted_probe": True},
                )
                final = writer.finish(
                    operator_success=None,
                    evaluator=evaluator,
                    failure_reason=None if succeeded else "automatic_criterion_not_met",
                )
                _write_native_payload(final, native_arrays)
                saved.append(final)
                print(f"saved {final}", flush=True)
            except BaseException:
                if writer.is_recording:
                    writer.discard()
                raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        task.close()
    return saved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RoboVerse to Studio canonical episode worker")
    parser.add_argument("--scene", required=True, choices=tuple(ROBOVERSE_TASKS))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--camera-profile-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = collect(args)
    except InterruptedError as error:
        print(str(error), file=sys.stderr, flush=True)
        return 130
    print(f"completed {len(paths)} RoboVerse episode(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
