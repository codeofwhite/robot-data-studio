from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from consumers.openpi_franka_joint8.phase_sampling import (
    DEFAULT_PHASE_PROBABILITIES,
    CountingWeightedSampler,
    assign_phases,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary(value: Any) -> dict[str, Any]:
    return {"shape": [int(item) for item in value.shape], "dtype": str(value.dtype)}


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse_training_metrics(output: str) -> list[dict[str, float | int]]:
    metrics = []
    for match in re.finditer(r"Step (\d+): ([^\r\n]+)", output):
        values: dict[str, float | int] = {"step": int(match.group(1))}
        for item in match.group(2).split(", "):
            key, value = item.split("=", maxsplit=1)
            values[key] = float(value)
        metrics.append(values)
    return metrics


class _Tee:
    def __init__(self, stream):
        self.stream = stream
        self.parts: list[str] = []

    def write(self, value: str) -> int:
        self.parts.append(value)
        return self.stream.write(value)

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return self.stream.isatty()


def _validate_paths(dataset_root: Path, base_checkpoint: Path) -> None:
    info_path = dataset_root / "meta" / "info.json"
    if not info_path.is_file():
        raise FileNotFoundError(f"LeRobot metadata is unavailable: {info_path}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("codebase_version") != "v2.1":
        raise ValueError(f"expected LeRobot v2.1, got {info.get('codebase_version')}")
    if not (base_checkpoint / "params").is_dir():
        raise FileNotFoundError(f"base checkpoint params are unavailable: {base_checkpoint}")


def _dataset_evidence(dataset_root: Path) -> dict[str, Any]:
    info = json.loads((dataset_root / "meta" / "info.json").read_text(encoding="utf-8"))
    return {
        "dataset_root": str(dataset_root),
        "total_episodes": int(info["total_episodes"]),
        "total_frames": int(info["total_frames"]),
        "codebase_version": str(info["codebase_version"]),
    }


def _install_local_dataset_loader(
    dataset_root: Path,
    *,
    sampling_strategy: str = "uniform",
    transition_radius: int = 2,
) -> dict[str, Any]:
    """Route OpenPI's pinned LeRobot loader to an explicit local root and PyAV."""
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
    from openpi import transforms
    from openpi.training import data_loader

    def create_local_dataset(data_config, action_horizon, model_config):
        del model_config
        if data_config.repo_id != dataset_root.name:
            raise ValueError(
                f"configured repo_id {data_config.repo_id!r} does not match {dataset_root.name!r}"
            )
        metadata = LeRobotDatasetMetadata(data_config.repo_id, root=dataset_root)
        dataset = LeRobotDataset(
            data_config.repo_id,
            root=dataset_root,
            delta_timestamps={
                key: [step / metadata.fps for step in range(action_horizon)]
                for key in data_config.action_sequence_keys
            },
            video_backend="pyav",
        )
        if data_config.prompt_from_task:
            dataset = data_loader.TransformedDataset(
                dataset,
                [transforms.PromptFromLeRobotTask(metadata.tasks)],
            )
        return dataset

    data_loader.create_torch_dataset = create_local_dataset
    runtime: dict[str, Any] = {"sampler": None}
    if sampling_strategy == "uniform":
        return runtime
    if sampling_strategy != "phase_balanced":
        raise ValueError(f"unknown sampling strategy: {sampling_strategy}")

    original_create_torch_data_loader = data_loader.create_torch_data_loader

    def create_phase_balanced_loader(
        data_config,
        model_config,
        action_horizon,
        batch_size,
        *,
        sharding=None,
        skip_norm_stats=False,
        shuffle=False,
        num_batches=None,
        num_workers=0,
        seed=0,
        framework="jax",
    ):
        del shuffle
        if framework != "jax":
            raise NotImplementedError("phase-balanced sampling currently supports the JAX trainer only")
        raw_dataset = data_loader.create_torch_dataset(data_config, action_horizon, model_config)
        base_dataset = raw_dataset
        while not hasattr(base_dataset, "hf_dataset") and hasattr(base_dataset, "_dataset"):
            base_dataset = base_dataset._dataset
        if not hasattr(base_dataset, "hf_dataset"):
            raise TypeError("phase-balanced sampling requires a LeRobot dataset")
        table = base_dataset.hf_dataset
        episodes = np.asarray(table["episode_index"], dtype=np.int64)
        frames = np.asarray(table["frame_index"], dtype=np.int64)
        actions = np.asarray(table["action"], dtype=np.float32)
        phases = assign_phases(
            episodes,
            frames,
            actions[:, 7],
            transition_radius=transition_radius,
        )
        sampler = CountingWeightedSampler(phases, DEFAULT_PHASE_PROBABILITIES, seed=seed)
        runtime["sampler"] = sampler
        transformed = data_loader.transform_dataset(
            raw_dataset,
            data_config,
            skip_norm_stats=skip_norm_stats,
        )
        local_batch_size = batch_size // data_loader.jax.process_count()
        torch_loader = data_loader.TorchDataLoader(
            transformed,
            local_batch_size=local_batch_size,
            sharding=sharding,
            sampler=sampler,
            num_batches=num_batches,
            num_workers=num_workers,
            seed=seed,
            framework=framework,
        )
        return data_loader.DataLoaderImpl(data_config, torch_loader)

    runtime["original_create_torch_data_loader"] = original_create_torch_data_loader
    data_loader.create_torch_data_loader = create_phase_balanced_loader
    return runtime


def _sampling_report(args) -> dict[str, Any]:
    sampler = args.sampling_runtime.get("sampler")
    if sampler is None:
        return {"strategy": "uniform"}
    result = sampler.report()
    result["transition_radius_frames"] = args.transition_radius
    return result


def _config(args):
    from consumers.openpi_franka_joint8.config import make_train_config

    return make_train_config(
        dataset_root=args.dataset_root,
        training_root=args.training_root,
        base_checkpoint=args.base_checkpoint,
        experiment_name=args.experiment_name,
        num_train_steps=args.num_train_steps,
        overwrite=getattr(args, "overwrite", False),
        resume=getattr(args, "resume", False),
    )


def compute_stats(args) -> dict[str, Any]:
    from openpi.shared import normalize
    from openpi.training import data_loader

    config = _config(args)
    data_config = config.data.create(config.assets_dirs, config.model)
    dataset = data_loader.create_torch_dataset(
        data_config,
        config.model.action_horizon,
        config.model,
    )
    dataset = data_loader.TransformedDataset(
        dataset,
        [
            *data_config.repack_transforms.inputs,
            *data_config.data_transforms.inputs,
        ],
    )
    stats = {key: normalize.RunningStats() for key in ("state", "actions")}
    for index in range(len(dataset)):
        sample = dataset[index]
        for key in stats:
            stats[key].update(np.asarray(sample[key]))
    result = {key: value.get_statistics() for key, value in stats.items()}
    for key, value in result.items():
        arrays = (value.mean, value.std, value.q01, value.q99)
        if value.mean.shape != (8,) or any(not np.isfinite(array).all() for array in arrays):
            raise ValueError(f"invalid {key} normalization statistics")
    output_dir = config.assets_dirs / data_config.asset_id
    normalize.save(output_dir, result)
    return {
        "stage": "norm_stats",
        "status": "passed",
        "frames": len(dataset),
        "output": str(output_dir / "norm_stats.json"),
        "statistics": json.loads(normalize.serialize_json(result))["norm_stats"],
    }


def preflight(args) -> dict[str, Any]:
    from openpi.training import data_loader

    config = _config(args)
    loader = data_loader.create_data_loader(
        config,
        shuffle=False,
        num_batches=1,
        skip_norm_stats=False,
    )
    observation, actions = next(iter(loader))
    if observation.state.shape != (1, 32) or actions.shape != (1, 10, 32):
        raise ValueError("OpenPI training batch does not match the pi0.5 model contract")
    return {
        "stage": "preflight",
        "status": "passed",
        "state": _summary(observation.state),
        "actions": _summary(actions),
        "images": {key: _summary(value) for key, value in observation.images.items()},
        "image_masks": {
            key: _summary(value) for key, value in observation.image_masks.items()
        },
        "tokenized_prompt": _summary(observation.tokenized_prompt),
        "sampling": _sampling_report(args),
    }


def train(args) -> dict[str, Any]:
    config = _config(args)
    dataset = _dataset_evidence(args.dataset_root)
    train_path = args.openpi_root / "scripts" / "train.py"
    spec = importlib.util.spec_from_file_location("studio_openpi_train", train_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load OpenPI train entrypoint: {train_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_jax_update = module.jax.config.update

    def update_jax_config(name, value):
        if name == "jax_compilation_cache_dir":
            value = str(args.training_root / "cache" / "jax")
        return original_jax_update(name, value)

    module.jax.config.update = update_jax_config

    stdout_capture = _Tee(sys.stdout)
    stderr_capture = _Tee(sys.stderr)
    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        module.main(config)
    metrics = _parse_training_metrics("".join(stdout_capture.parts + stderr_capture.parts))
    steps = sorted(path for path in config.checkpoint_dir.iterdir() if path.name.isdigit())
    if not steps:
        raise RuntimeError(f"training did not produce a checkpoint under {config.checkpoint_dir}")
    checkpoint = steps[-1]
    return {
        "stage": "train",
        "status": "passed",
        "config_name": config.name,
        "experiment_name": config.exp_name,
        "num_train_steps": config.num_train_steps,
        "checkpoint": str(checkpoint),
        "base_checkpoint": str(args.base_checkpoint),
        "seed": config.seed,
        "batch_size": config.batch_size,
        "metrics": metrics,
        "dataset": dataset,
        "sampling": _sampling_report(args),
        "evidence": (
            "multi_episode_lora_finetune"
            if dataset["total_episodes"] > 1
            else "one_episode_pipeline_sanity"
        ),
        "review_status": "SELF_REVIEWED_PROVISIONAL",
    }


def infer(args) -> dict[str, Any]:
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    from openpi.policies import policy_config

    if args.checkpoint is None:
        raise ValueError("--checkpoint is required for infer")
    config = _config(args)
    dataset = LeRobotDataset(
        args.dataset_root.name,
        root=args.dataset_root,
        video_backend="pyav",
    )
    sample = dataset[0]
    policy = policy_config.create_trained_policy(
        config,
        args.checkpoint,
        sample_kwargs={"num_steps": args.inference_steps},
    )
    output = policy.infer(
        {
            "observation/image": sample["observation.images.base"],
            "observation/wrist_image": sample["observation.images.wrist"],
            "observation/state": np.asarray(sample["observation.state"], dtype=np.float32),
            "prompt": sample["task"],
        }
    )
    actions = np.asarray(output["actions"])
    if actions.shape != (10, 8) or not np.isfinite(actions).all():
        raise ValueError(f"invalid Franka joint8 policy output: {actions.shape}")
    dataset = _dataset_evidence(args.dataset_root)
    return {
        "stage": "checkpoint_inference",
        "status": "passed",
        "checkpoint": str(args.checkpoint),
        "instruction": str(sample["task"]),
        "actions": _summary(actions),
        "actions_finite": True,
        "contract_compatible": True,
        "deployment_compatible": True,
        "closed_loop_validated": False,
        "dataset": dataset,
        "training_evidence": (
            "multi_episode_checkpoint_inference"
            if dataset["total_episodes"] > 1
            else "one_episode_pipeline_sanity"
        ),
        "policy_infer_ms": float(output["policy_timing"]["infer_ms"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenPI Franka joint8 training bridge")
    parser.add_argument("stage", choices=("stats", "preflight", "train", "infer"))
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--openpi-root", type=Path, default=Path("/data/zhanghejun/openpi"))
    parser.add_argument("--experiment-name", default="seed0_sanity")
    parser.add_argument("--num-train-steps", type=int, default=10)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--inference-steps", type=int, default=2)
    parser.add_argument(
        "--sampling-strategy",
        choices=("uniform", "phase_balanced"),
        default="uniform",
    )
    parser.add_argument("--transition-radius", type=int, default=2)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.dataset_root = args.dataset_root.expanduser().resolve()
    args.training_root = args.training_root.expanduser().resolve()
    args.base_checkpoint = args.base_checkpoint.expanduser().resolve()
    args.openpi_root = args.openpi_root.expanduser().resolve()
    if args.checkpoint is not None:
        args.checkpoint = args.checkpoint.expanduser().resolve()
    os.environ.setdefault(
        "HF_DATASETS_CACHE",
        str(args.training_root / "cache" / "huggingface" / "datasets"),
    )
    os.environ.setdefault(
        "JAX_COMPILATION_CACHE_DIR",
        str(args.training_root / "cache" / "jax"),
    )
    _validate_paths(args.dataset_root, args.base_checkpoint)
    if args.transition_radius < 0:
        parser.error("--transition-radius must be non-negative")
    args.sampling_runtime = _install_local_dataset_loader(
        args.dataset_root,
        sampling_strategy=args.sampling_strategy,
        transition_radius=args.transition_radius,
    )
    started_at = _now()
    try:
        runners = {"stats": compute_stats, "preflight": preflight, "train": train, "infer": infer}
        report = runners[args.stage](args)
        report.update(
            started_at=started_at,
            finished_at=_now(),
            python=sys.version,
            platform=platform.platform(),
            cuda_visible_devices=os.getenv("CUDA_VISIBLE_DEVICES"),
        )
    except Exception as error:
        report = {
            "stage": args.stage,
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
            "started_at": started_at,
            "finished_at": _now(),
        }
        _write_report(args.report, report)
        raise
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
