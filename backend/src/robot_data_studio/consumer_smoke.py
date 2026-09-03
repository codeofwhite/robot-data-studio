from __future__ import annotations

import argparse
import json
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shape(value: Any) -> list[int] | None:
    shape = getattr(value, "shape", None)
    return None if shape is None else [int(item) for item in shape]


def _dtype(value: Any) -> str | None:
    dtype = getattr(value, "dtype", None)
    return None if dtype is None else str(dtype)


def _tensor_summary(value: Any) -> dict[str, Any]:
    return {"shape": _shape(value), "dtype": _dtype(value)}


def smoke_openpi(dataset_root: Path, repo_id: str) -> dict[str, Any]:
    import jax
    import numpy as np
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
    from openpi import transforms
    from openpi.models.model import Observation
    from openpi.models.pi0_config import Pi0Config
    from openpi.policies.libero_policy import LiberoInputs
    from openpi.training.config import ModelTransformFactory

    metadata = LeRobotDatasetMetadata(repo_id, root=dataset_root)
    if str(metadata._version) != "2.1":
        raise ValueError(f"OpenPI requires LeRobot v2.1, got {metadata._version}")
    model_config = Pi0Config()
    dataset = LeRobotDataset(
        repo_id,
        root=dataset_root,
        video_backend="pyav",
        delta_timestamps={
            "action": [step / metadata.fps for step in range(model_config.action_horizon)]
        },
    )
    sample = dataset[0]
    required_cameras = ("observation.images.base", "observation.images.wrist")
    missing = [key for key in required_cameras if key not in sample]
    if missing:
        raise KeyError(f"OpenPI Franka view is missing cameras: {missing}")
    input_data = {
        "observation/image": sample["observation.images.base"],
        "observation/wrist_image": sample["observation.images.wrist"],
        "observation/state": np.asarray(sample["observation.state"], dtype=np.float32),
        "actions": np.asarray(sample["action"], dtype=np.float32),
        "prompt": sample["task"],
    }
    pipeline = transforms.compose(
        [
            LiberoInputs(model_type=model_config.model_type),
            transforms.DeltaActions(transforms.make_bool_mask(7, -1)),
            *ModelTransformFactory()(model_config).inputs,
        ]
    )
    transformed = pipeline(input_data)
    batch = jax.tree.map(
        lambda value: np.expand_dims(value, 0) if hasattr(value, "shape") else value,
        transformed,
    )
    observation = Observation.from_dict(batch)
    actions = batch["actions"]
    expected_observation, expected_actions = model_config.inputs_spec(batch_size=1)
    if tuple(observation.state.shape) != tuple(expected_observation.state.shape):
        raise ValueError("OpenPI state does not match the pi0 model input spec")
    if tuple(actions.shape) != tuple(expected_actions.shape):
        raise ValueError("OpenPI actions do not match the pi0 model input spec")
    for key, expected in expected_observation.images.items():
        if tuple(observation.images[key].shape) != tuple(expected.shape):
            raise ValueError(f"OpenPI image {key} does not match the pi0 model input spec")
    return {
        "consumer": "openpi",
        "consumer_version": "local-openpi-lerobot-v2.1",
        "video_backend": "pyav",
        "dataset_format": "lerobot_v2.1",
        "dataset": {
            "repo_id": repo_id,
            "episodes": metadata.total_episodes,
            "frames": metadata.total_frames,
            "fps": metadata.fps,
        },
        "instruction": str(sample["task"]),
        "source": {
            "state": _tensor_summary(sample["observation.state"]),
            "action": _tensor_summary(sample["action"]),
            "images": {key: _tensor_summary(sample[key]) for key in required_cameras},
        },
        "model_input": {
            "state": _tensor_summary(observation.state),
            "action": _tensor_summary(actions),
            "images": {key: _tensor_summary(value) for key, value in observation.images.items()},
            "image_masks": {
                key: _tensor_summary(value) for key, value in observation.image_masks.items()
            },
            "tokenized_prompt": _tensor_summary(observation.tokenized_prompt),
            "tokenized_prompt_mask": _tensor_summary(observation.tokenized_prompt_mask),
        },
    }


def smoke_fastwam(dataset_root: Path, repo_id: str) -> dict[str, Any]:
    from torch.utils.data import default_collate

    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    from lerobot.policies.fastwam.configuration_fastwam import FastWAMConfig
    from lerobot.policies.fastwam.modeling_fastwam import FastWAMPolicy, _stack_video_from_images
    from lerobot.policies.fastwam.processor_fastwam import make_fastwam_pre_post_processors

    metadata = LeRobotDatasetMetadata(repo_id, root=dataset_root)
    if str(metadata._version) != "3.0":
        raise ValueError(f"FastWAM requires LeRobot v3.0, got {metadata._version}")
    config = FastWAMConfig(
        action_dim=8,
        proprio_dim=8,
        action_horizon=32,
        n_action_steps=10,
        num_video_frames=33,
        action_video_freq_ratio=4,
        image_size=(224, 448),
        base_model_id=None,
        load_text_encoder=False,
        device="cpu",
        torch_dtype="float32",
    )
    config.set_dataset_feature_metadata(metadata.features)
    delta_timestamps = {
        key: [step / metadata.fps for step in config.observation_delta_indices]
        for key in metadata.video_keys
    }
    delta_timestamps["action"] = [step / metadata.fps for step in config.action_delta_indices]
    dataset = LeRobotDataset(
        repo_id,
        root=dataset_root,
        delta_timestamps=delta_timestamps,
        video_backend="pyav",
    )
    sample = dataset[0]
    preprocessor, _ = make_fastwam_pre_post_processors(config, dataset_stats=metadata.stats)
    processed = preprocessor(default_collate([sample]))
    video = _stack_video_from_images(processed, config)
    expected_video_frames = config.model_video_frames
    if processed["action"].shape[-2:] != (config.action_horizon, config.action_dim):
        raise ValueError("FastWAM action batch has the wrong horizon or dimension")
    if processed["observation.state"].shape[-1] != config.proprio_dim:
        raise ValueError("FastWAM proprio batch has the wrong dimension")
    if processed["action"].shape[0] != 1:
        raise ValueError("FastWAM smoke must contain exactly one batch item")
    if video.shape[0] != 1:
        raise ValueError("FastWAM video must preserve the one-item batch dimension")
    if video.shape[2] != expected_video_frames:
        raise ValueError("FastWAM video batch has the wrong temporal dimension")
    image_keys = sorted(config.image_features)
    return {
        "consumer": "fastwam",
        "consumer_version": f"{FastWAMPolicy.__module__}.{FastWAMPolicy.__name__}",
        "video_backend": "pyav",
        "dataset_format": "lerobot_v3.0",
        "dataset": {
            "repo_id": repo_id,
            "episodes": metadata.total_episodes,
            "frames": metadata.total_frames,
            "fps": metadata.fps,
        },
        "instruction": str(sample["task"]),
        "source": {
            "state": _tensor_summary(sample["observation.state"]),
            "action": _tensor_summary(sample["action"]),
            "images": {key: _tensor_summary(sample[key]) for key in image_keys},
        },
        "processor_batch": {
            "state": _tensor_summary(processed["observation.state"]),
            "action": _tensor_summary(processed["action"]),
            "images": {key: _tensor_summary(processed[key]) for key in image_keys},
            "video": _tensor_summary(video),
            "task_type": type(processed.get("task")).__name__,
        },
        "policy_config": {
            "action_dim": config.action_dim,
            "proprio_dim": config.proprio_dim,
            "action_horizon": config.action_horizon,
            "num_video_frames": config.num_video_frames,
            "model_video_frames": config.model_video_frames,
            "action_video_freq_ratio": config.action_video_freq_ratio,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real training-consumer batch smoke")
    parser.add_argument("--consumer", choices=("openpi", "fastwam"), required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    started_at = _now()
    report: dict[str, Any]
    try:
        runner = smoke_openpi if args.consumer == "openpi" else smoke_fastwam
        report = runner(args.dataset_root.expanduser().resolve(), args.repo_id)
        report.update(status="passed", started_at=started_at, finished_at=_now())
        exit_code = 0
    except Exception as error:
        report = {
            "consumer": args.consumer,
            "status": "failed",
            "dataset_root": str(args.dataset_root),
            "repo_id": args.repo_id,
            "python": sys.version,
            "platform": platform.platform(),
            "started_at": started_at,
            "finished_at": _now(),
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
