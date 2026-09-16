from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import h5py
import numpy as np
import torch

from .dataset import (
    ACTION_DIM,
    OBSERVATION_DIM,
    ObservationNormalizer,
    assert_disjoint_seeds,
)
from .model import StateActionChunkMLP


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _scalar_bool(value: Any) -> bool:
    return bool(_to_numpy(value).reshape(-1)[0])


def _scalar_int(value: Any) -> int:
    return int(_to_numpy(value).reshape(-1)[0])


def observation_vector(observation: dict[str, Any]) -> np.ndarray:
    try:
        parts = (
            _to_numpy(observation["agent"]["qpos"]).reshape(-1),
            _to_numpy(observation["agent"]["qvel"]).reshape(-1),
            _to_numpy(observation["extra"]["obj_pose"]).reshape(-1),
            _to_numpy(observation["extra"]["goal_pos"]).reshape(-1),
        )
    except KeyError as error:
        raise ValueError(f"PickCube observation is missing {error}") from error
    vector = np.concatenate(parts).astype(np.float32)
    if vector.shape != (OBSERVATION_DIM,):
        raise ValueError(
            f"PickCube observation has shape {vector.shape}, expected {(OBSERVATION_DIM,)}"
        )
    if not np.isfinite(vector).all():
        raise ValueError("PickCube observation contains non-finite values")
    return vector


def classify_failure(
    *,
    success: bool,
    ever_grasped: bool,
    ever_placed: bool,
    final_placed: bool,
    final_static: bool,
) -> str | None:
    if success:
        return None
    if not ever_grasped:
        return "never_grasped"
    if not ever_placed:
        return "grasped_but_not_placed"
    if final_placed and not final_static:
        return "placed_but_not_static"
    return "placed_then_lost"


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    probability = successes / total
    denominator = 1.0 + z * z / total
    center = (probability + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return (center - margin, center + margin)


def paired_exact_greater(policy: list[bool], baseline: list[bool]) -> dict[str, float | int]:
    if len(policy) != len(baseline):
        raise ValueError("paired outcomes must have the same length")
    policy_only = sum(p and not b for p, b in zip(policy, baseline, strict=True))
    baseline_only = sum(b and not p for p, b in zip(policy, baseline, strict=True))
    discordant = policy_only + baseline_only
    if discordant == 0:
        p_value = 1.0
    else:
        p_value = sum(
            math.comb(discordant, value)
            for value in range(policy_only, discordant + 1)
        ) / (2**discordant)
    return {
        "policy_only_successes": policy_only,
        "baseline_only_successes": baseline_only,
        "discordant_pairs": discordant,
        "one_sided_exact_p_value": p_value,
    }


def _official_entries(metadata_path: Path, *, offset: int, count: int) -> list[dict[str, Any]]:
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    env_info = payload.get("env_info") or {}
    if env_info.get("env_id") != "PickCube-v1":
        raise ValueError("official metadata is not PickCube-v1")
    env_kwargs = env_info.get("env_kwargs") or {}
    if env_kwargs.get("control_mode") != "pd_joint_delta_pos":
        raise ValueError("official metadata has the wrong control mode")
    successful = [episode for episode in payload.get("episodes", []) if episode.get("success")]
    selected = successful[offset : offset + count]
    if len(selected) != count:
        raise ValueError(
            f"official metadata cannot provide {count} successful episodes at offset {offset}"
        )
    seeds = [int(entry["episode_seed"]) for entry in selected]
    if len(seeds) != len(set(seeds)):
        raise ValueError("held-out evaluation seeds are not unique")
    return selected


def _make_env(sim_backend: str):
    import gymnasium as gym
    import mani_skill.envs  # noqa: F401

    kwargs: dict[str, Any] = {
        "num_envs": 1,
        "obs_mode": "state_dict",
        "control_mode": "pd_joint_delta_pos",
        "sim_backend": sim_backend,
        "max_episode_steps": 50,
        "reconfiguration_freq": 1,
    }
    if sim_backend == "physx_cpu":
        kwargs["render_backend"] = "cpu"
    return gym.make("PickCube-v1", **kwargs)


def _episode_result(
    seed: int,
    mode: str,
    info: dict[str, Any],
    *,
    success: bool,
    ever_grasped: bool,
    ever_placed: bool,
    minimum_goal_distance_m: float,
) -> dict[str, Any]:
    final_grasped = _scalar_bool(info["is_grasped"])
    final_placed = _scalar_bool(info["is_obj_placed"])
    final_static = _scalar_bool(info["is_robot_static"])
    return {
        "seed": seed,
        "mode": mode,
        "success": success,
        "steps": _scalar_int(info["elapsed_steps"]),
        "failure_reason": classify_failure(
            success=success,
            ever_grasped=ever_grasped,
            ever_placed=ever_placed,
            final_placed=final_placed,
            final_static=final_static,
        ),
        "ever_grasped": ever_grasped,
        "ever_placed": ever_placed,
        "final_grasped": final_grasped,
        "final_placed": final_placed,
        "final_static": final_static,
        "minimum_goal_distance_m": minimum_goal_distance_m,
    }


def _run_reset_only(
    env: Any,
    entries: list[dict[str, Any]],
    *,
    mode: str,
    action_fn: Callable[[dict[str, Any]], np.ndarray],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in entries:
        seed = int(entry["episode_seed"])
        observation, info = env.reset(seed=seed)
        ever_grasped = _scalar_bool(info["is_grasped"])
        ever_placed = _scalar_bool(info["is_obj_placed"])
        success = _scalar_bool(info["success"])
        minimum_distance = float("inf")
        for _ in range(50):
            action = np.asarray(action_fn(observation), dtype=np.float32)
            if action.shape != (ACTION_DIM,):
                raise ValueError(f"{mode} action has shape {action.shape}")
            if not np.isfinite(action).all() or np.any(np.abs(action) > 1.000001):
                raise ValueError(f"{mode} produced an invalid normalized action")
            observation, _, terminated, truncated, info = env.step(action)
            extra = observation["extra"]
            object_position = _to_numpy(extra["obj_pose"]).reshape(-1)[:3]
            goal_position = _to_numpy(extra["goal_pos"]).reshape(-1)
            minimum_distance = min(
                minimum_distance, float(np.linalg.norm(object_position - goal_position))
            )
            ever_grasped = ever_grasped or _scalar_bool(info["is_grasped"])
            ever_placed = ever_placed or _scalar_bool(info["is_obj_placed"])
            success = success or _scalar_bool(info["success"])
            if success or _scalar_bool(terminated) or _scalar_bool(truncated):
                break
        results.append(
            _episode_result(
                seed,
                mode,
                info,
                success=success,
                ever_grasped=ever_grasped,
                ever_placed=ever_placed,
                minimum_goal_distance_m=minimum_distance,
            )
        )
    return results


def _demo_state(group: h5py.Group, device: torch.device) -> dict[str, dict[str, torch.Tensor]]:
    state: dict[str, dict[str, torch.Tensor]] = {}
    for section in ("actors", "articulations"):
        state[section] = {
            name: torch.as_tensor(
                np.asarray(dataset[0], dtype=np.float32), device=device
            ).reshape(1, -1)
            for name, dataset in group["env_states"][section].items()
        }
    return state


def _state_fidelity(
    reset_state: dict[str, dict[str, torch.Tensor]],
    demo_state: dict[str, dict[str, torch.Tensor]],
) -> dict[str, float]:
    result: dict[str, float] = {}
    for section, names in (
        ("actors", ("cube", "goal_site")),
        ("articulations", ("panda",)),
    ):
        for name in names:
            delta = reset_state[section][name] - demo_state[section][name]
            result[f"{section}/{name}_max_abs"] = float(
                torch.max(torch.abs(delta)).detach().cpu()
            )
    return result


def _run_restored_demo_ceiling(
    env: Any,
    entries: list[dict[str, Any]],
    demo_h5: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    unwrapped = env.unwrapped
    device = torch.device(unwrapped.device)
    with h5py.File(demo_h5, "r") as demos:
        for entry in entries:
            seed = int(entry["episode_seed"])
            key = f"traj_{int(entry['episode_id'])}"
            if key not in demos:
                raise ValueError(f"official demo is missing {key}")
            group = demos[key]
            actions = np.asarray(group["actions"], dtype=np.float32)
            _, info = env.reset(seed=seed)
            reset_state = unwrapped.get_state_dict()
            demo_state = _demo_state(group, device)
            fidelity = _state_fidelity(reset_state, demo_state)
            unwrapped.set_state_dict(demo_state)
            unwrapped.goal_pos = demo_state["actors"]["goal_site"][:, :3]

            ever_grasped = _scalar_bool(info["is_grasped"])
            ever_placed = _scalar_bool(info["is_obj_placed"])
            success = False
            minimum_distance = float("inf")
            for raw_action in actions[:50]:
                observation, _, terminated, truncated, info = env.step(raw_action)
                extra = observation["extra"]
                object_position = _to_numpy(extra["obj_pose"]).reshape(-1)[:3]
                goal_position = _to_numpy(extra["goal_pos"]).reshape(-1)
                minimum_distance = min(
                    minimum_distance,
                    float(np.linalg.norm(object_position - goal_position)),
                )
                ever_grasped = ever_grasped or _scalar_bool(info["is_grasped"])
                ever_placed = ever_placed or _scalar_bool(info["is_obj_placed"])
                success = success or _scalar_bool(info["success"])
                if success or _scalar_bool(terminated) or _scalar_bool(truncated):
                    break
            result = _episode_result(
                seed,
                "official_demo_replay_restored_ceiling",
                info,
                success=success,
                ever_grasped=ever_grasped,
                ever_placed=ever_placed,
                minimum_goal_distance_m=minimum_distance,
            )
            result["source_demo_trajectory"] = key
            result["initial_state_restored"] = True
            result["reset_vs_demo_initial_state"] = fidelity
            results.append(result)
    return results


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    successes = sum(bool(result["success"]) for result in results)
    low, high = wilson_interval(successes, len(results))
    failures = Counter(
        str(result["failure_reason"])
        for result in results
        if result["failure_reason"] is not None
    )
    return {
        "successes": successes,
        "episodes": len(results),
        "success_rate": successes / len(results) if results else 0.0,
        "wilson_95_interval": [low, high],
        "failure_breakdown": dict(sorted(failures.items())),
        "episodes_detail": results,
    }


def evaluate(args: argparse.Namespace) -> Path:
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if checkpoint.get("format") != "robot_data_studio_roboverse_state_bc_v1":
        raise ValueError("unsupported checkpoint format")
    configuration = checkpoint["model"]
    model = StateActionChunkMLP(**configuration)
    model.load_state_dict(checkpoint["model_state_dict"])
    if args.model_device == "auto":
        model_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        model_device = torch.device(args.model_device)
    model.to(model_device).eval()
    normalizer = ObservationNormalizer.load(args.checkpoint.parent / "normalizer.npz")

    entries = _official_entries(
        args.demo_metadata,
        offset=args.evaluation_demo_offset,
        count=args.episodes,
    )
    evaluation_seeds = [int(entry["episode_seed"]) for entry in entries]
    assert_disjoint_seeds(
        checkpoint["train_seeds"],
        checkpoint["validation_seeds"],
        evaluation_seeds,
    )

    def policy_action(observation: dict[str, Any]) -> np.ndarray:
        vector = observation_vector(observation)
        normalized = normalizer.transform_numpy(vector)
        tensor = torch.as_tensor(normalized, device=model_device).unsqueeze(0)
        with torch.no_grad():
            chunk = model(tensor)[0]
        return chunk[0].detach().cpu().numpy()

    started_at = _utc_now()
    policy_env = _make_env(args.sim_backend)
    try:
        policy_results = _run_reset_only(
            policy_env, entries, mode="policy_closed_loop", action_fn=policy_action
        )
    finally:
        policy_env.close()
    zero_env = _make_env(args.sim_backend)
    try:
        zero_results = _run_reset_only(
            zero_env,
            entries,
            mode="zero_action",
            action_fn=lambda _observation: np.zeros(ACTION_DIM, dtype=np.float32),
        )
    finally:
        zero_env.close()
    ceiling_env = _make_env(args.sim_backend)
    try:
        ceiling_results = _run_restored_demo_ceiling(
            ceiling_env, entries, args.demo_h5
        )
    finally:
        ceiling_env.close()

    policy_success = [bool(result["success"]) for result in policy_results]
    zero_success = [bool(result["success"]) for result in zero_results]
    comparison = paired_exact_greater(policy_success, zero_success)
    policy_count = sum(policy_success)
    zero_count = sum(zero_success)
    promotion_passed = (
        policy_count >= 10
        and policy_count > zero_count
        and float(comparison["one_sided_exact_p_value"]) < 0.05
    )
    report = {
        "status": "completed",
        "evidence_label": (
            "policy_capability_gate_passed"
            if promotion_passed
            else "training_and_closed_loop_pipeline_completed"
        ),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_git": checkpoint["git"],
        "evaluation_git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("torch", "numpy", "gymnasium", "mani-skill", "h5py")
        },
        "environment": {
            "gym_id": "PickCube-v1",
            "control_mode": "pd_joint_delta_pos",
            "observation_mode": "state_dict",
            "sim_backend": args.sim_backend,
            "episodes": args.episodes,
            "evaluation_successful_demo_offset": args.evaluation_demo_offset,
            "model_initial_state_restored": False,
            "model_action_replay": False,
            "zero_initial_state_restored": False,
            "ceiling_initial_state_restored": True,
            "ceiling_note": (
                "The official demo replay ceiling restores recorded initial state and is "
                "not a distribution-matched policy baseline."
            ),
        },
        "seed_audit": {
            "train": checkpoint["train_seeds"],
            "validation": checkpoint["validation_seeds"],
            "evaluation": evaluation_seeds,
            "disjoint": True,
        },
        "policy": _summary(policy_results),
        "zero_action": _summary(zero_results),
        "official_demo_replay_restored_ceiling": _summary(ceiling_results),
        "policy_vs_zero_action": comparison,
        "promotion_gate": {
            "minimum_successes": 10,
            "requires_more_successes_than_zero_action": True,
            "one_sided_exact_p_value_below": 0.05,
            "passed": promotion_passed,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"evaluation output already exists: {args.output}")
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "evidence_label": report["evidence_label"],
                "policy_successes": report["policy"]["successes"],
                "zero_action_successes": report["zero_action"]["successes"],
                "ceiling_successes": report[
                    "official_demo_replay_restored_ceiling"
                ]["successes"],
                "promotion_gate_passed": promotion_passed,
                "output": str(args.output.resolve()),
            },
            indent=2,
        )
    )
    return args.output


def build_parser() -> argparse.ArgumentParser:
    demo_root = PROJECT_ROOT / "data/cache/maniskill/PickCube-v1/rl"
    demo_stem = "trajectory.none.pd_joint_delta_pos.physx_cuda"
    parser = argparse.ArgumentParser(
        description="Evaluate state BC in native ManiSkill PickCube closed loop"
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--evaluation-demo-offset", type=int, default=48)
    parser.add_argument("--sim-backend", choices=("physx_cuda", "physx_cpu"), default="physx_cuda")
    parser.add_argument("--model-device", default="auto")
    parser.add_argument("--demo-h5", type=Path, default=demo_root / f"{demo_stem}.h5")
    parser.add_argument(
        "--demo-metadata", type=Path, default=demo_root / f"{demo_stem}.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data/evaluations/roboverse_state_bc/pickcube_bc_v1.json",
    )
    return parser


def main() -> None:
    evaluate(build_parser().parse_args())


if __name__ == "__main__":
    main()
