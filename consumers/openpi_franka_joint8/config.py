from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import numpy as np
from openpi import transforms
from openpi.models import model as model_api
from openpi.models import pi0_config
from openpi.training import config as training_config
from openpi.training import optimizer
from openpi.training import weight_loaders
from typing_extensions import override


CONFIG_NAME = "pi05_franka_joint8_lora"
ASSET_ID = "openpi_franka_joint8"
ACTION_DIM = 8
ACTION_HORIZON = 10
JOINT_DELTA_MASK = transforms.make_bool_mask(7, -1)


def _parse_image(value: Any) -> np.ndarray:
    image = np.asarray(value)
    if np.issubdtype(image.dtype, np.floating):
        image = (255 * image).astype(np.uint8)
    if image.ndim != 3:
        raise ValueError(f"expected an RGB image, got shape {image.shape}")
    if image.shape[0] == 3:
        image = np.transpose(image, (1, 2, 0))
    if image.shape[-1] != 3:
        raise ValueError(f"expected three RGB channels, got shape {image.shape}")
    return image


@dataclasses.dataclass(frozen=True)
class FrankaJoint8Inputs(transforms.DataTransformFn):
    model_type: model_api.ModelType

    def __call__(self, data: dict) -> dict:
        base_image = _parse_image(data["observation/image"])
        wrist_image = _parse_image(data["observation/wrist_image"])
        state = np.asarray(data["observation/state"], dtype=np.float32)
        if state.shape != (ACTION_DIM,):
            raise ValueError(f"Franka joint8 state must have shape (8,), got {state.shape}")
        result = {
            "state": state,
            "image": {
                "base_0_rgb": base_image,
                "left_wrist_0_rgb": wrist_image,
                "right_wrist_0_rgb": np.zeros_like(base_image),
            },
            "image_mask": {
                "base_0_rgb": np.True_,
                "left_wrist_0_rgb": np.True_,
                "right_wrist_0_rgb": np.False_,
            },
        }
        if "actions" in data:
            actions = np.asarray(data["actions"], dtype=np.float32)
            if actions.shape[-1] != ACTION_DIM:
                raise ValueError(f"Franka joint8 actions must end in dimension 8, got {actions.shape}")
            result["actions"] = actions
        if "prompt" in data:
            result["prompt"] = data["prompt"]
        return result


@dataclasses.dataclass(frozen=True)
class FrankaJoint8Outputs(transforms.DataTransformFn):
    def __call__(self, data: dict) -> dict:
        return {"actions": np.asarray(data["actions"], dtype=np.float32)[..., :ACTION_DIM]}


@dataclasses.dataclass(frozen=True)
class LeRobotFrankaJoint8DataConfig(training_config.DataConfigFactory):
    @override
    def create(
        self,
        assets_dirs: Path,
        model_config: model_api.BaseModelConfig,
    ) -> training_config.DataConfig:
        repack = transforms.Group(
            inputs=[
                transforms.RepackTransform(
                    {
                        "observation/image": "observation.images.base",
                        "observation/wrist_image": "observation.images.wrist",
                        "observation/state": "observation.state",
                        "actions": "action",
                        "prompt": "prompt",
                    }
                )
            ]
        )
        data_transforms = transforms.Group(
            inputs=[
                FrankaJoint8Inputs(model_type=model_config.model_type),
                transforms.DeltaActions(JOINT_DELTA_MASK),
            ],
            outputs=[
                transforms.AbsoluteActions(JOINT_DELTA_MASK),
                FrankaJoint8Outputs(),
            ],
        )
        return dataclasses.replace(
            self.create_base_config(assets_dirs, model_config),
            repack_transforms=repack,
            data_transforms=data_transforms,
            model_transforms=training_config.ModelTransformFactory()(model_config),
            action_sequence_keys=("action",),
        )


def make_train_config(
    *,
    dataset_root: Path,
    training_root: Path,
    base_checkpoint: Path,
    experiment_name: str = "seed0_sanity",
    num_train_steps: int = 10,
    overwrite: bool = False,
    resume: bool = False,
) -> training_config.TrainConfig:
    if num_train_steps < 1:
        raise ValueError("num_train_steps must be positive")
    model = pi0_config.Pi0Config(
        pi05=True,
        action_horizon=ACTION_HORIZON,
        discrete_state_input=False,
        paligemma_variant="gemma_2b_lora",
        action_expert_variant="gemma_300m_lora",
    )
    return training_config.TrainConfig(
        name=CONFIG_NAME,
        exp_name=experiment_name,
        model=model,
        data=LeRobotFrankaJoint8DataConfig(
            repo_id=dataset_root.name,
            assets=training_config.AssetsConfig(asset_id=ASSET_ID),
            base_config=training_config.DataConfig(prompt_from_task=True),
        ),
        weight_loader=weight_loaders.CheckpointWeightLoader(
            str(base_checkpoint.expanduser().resolve() / "params")
        ),
        freeze_filter=model.get_freeze_filter(),
        lr_schedule=optimizer.CosineDecaySchedule(
            warmup_steps=1,
            peak_lr=1e-5,
            decay_steps=max(num_train_steps, 2),
            decay_lr=1e-5,
        ),
        optimizer=optimizer.AdamW(clip_gradient_norm=1.0),
        ema_decay=None,
        batch_size=1,
        num_workers=0,
        num_train_steps=num_train_steps,
        log_interval=1,
        save_interval=num_train_steps,
        keep_period=None,
        overwrite=overwrite,
        resume=resume,
        wandb_enabled=False,
        seed=0,
        fsdp_devices=1,
        assets_base_dir=str(training_root / "assets"),
        checkpoint_base_dir=str(training_root / "checkpoints"),
        policy_metadata={
            "dataset_profile": "openpi_franka_joint8",
            "state_dimension": ACTION_DIM,
            "action_dimension": ACTION_DIM,
            "action_representation": "delta_joint7_plus_absolute_gripper_for_model",
            "policy_output_representation": "absolute_franka_joint8",
        },
    )
