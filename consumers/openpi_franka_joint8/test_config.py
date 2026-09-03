from pathlib import Path

import numpy as np

from openpi import transforms
from openpi.models import model as model_api

from consumers.openpi_franka_joint8.config import (
    ACTION_HORIZON,
    CONFIG_NAME,
    JOINT_DELTA_MASK,
    FrankaJoint8Inputs,
    FrankaJoint8Outputs,
    make_train_config,
)
from consumers.openpi_franka_joint8.run import _parse_training_metrics


def test_joint_delta_round_trip_keeps_gripper_absolute():
    state = np.arange(8, dtype=np.float32)
    actions = np.tile(state, (ACTION_HORIZON, 1))
    actions[:, :7] += 0.25
    actions[:, 7] = np.linspace(0.0, 1.0, ACTION_HORIZON)
    source = {
        "observation/image": np.zeros((3, 4, 5), dtype=np.float32),
        "observation/wrist_image": np.zeros((3, 4, 5), dtype=np.float32),
        "observation/state": state,
        "actions": actions,
        "prompt": "pick and place",
    }
    adapted = FrankaJoint8Inputs(model_api.ModelType.PI05)(source)
    delta = transforms.DeltaActions(JOINT_DELTA_MASK)(adapted)

    np.testing.assert_allclose(delta["actions"][:, :7], 0.25)
    np.testing.assert_allclose(delta["actions"][:, 7], actions[:, 7])
    absolute = transforms.AbsoluteActions(JOINT_DELTA_MASK)(delta)
    output = FrankaJoint8Outputs()(absolute)
    np.testing.assert_allclose(output["actions"], actions)
    assert output["actions"].dtype == np.float32


def test_training_config_is_single_gpu_lora_and_offline(tmp_path: Path):
    config = make_train_config(
        dataset_root=tmp_path / "dataset",
        training_root=tmp_path / "training",
        base_checkpoint=tmp_path / "pi05_libero",
    )

    assert config.name == CONFIG_NAME
    assert config.model.pi05 is True
    assert config.model.action_horizon == ACTION_HORIZON
    assert config.model.action_dim == 32
    assert config.model.paligemma_variant.endswith("_lora")
    assert config.model.action_expert_variant.endswith("_lora")
    assert config.batch_size == 1
    assert config.num_workers == 0
    assert config.fsdp_devices == 1
    assert config.wandb_enabled is False
    assert str(config.weight_loader.params_path).endswith("pi05_libero/params")
    data_config = config.data.create(config.assets_dirs, config.model)
    assert data_config.action_sequence_keys == ("action",)


def test_training_metrics_are_parsed_from_upstream_progress_output():
    metrics = _parse_training_metrics(
        "Step 0: grad_norm=1.6124, loss=0.2718, param_norm=1833.3756\n"
        "Step 1: grad_norm=0.4880, loss=0.0740, param_norm=1833.3757\n"
    )

    assert metrics == [
        {"step": 0, "grad_norm": 1.6124, "loss": 0.2718, "param_norm": 1833.3756},
        {"step": 1, "grad_norm": 0.4880, "loss": 0.0740, "param_norm": 1833.3757},
    ]
