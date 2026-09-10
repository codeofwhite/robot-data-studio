from __future__ import annotations

import numpy as np
import torch

from consumers.openpi_franka_joint8.gripper_event_head import (
    GripperEventHead,
    GripperOverridePolicy,
    _image_tensor,
)


def test_gripper_head_outputs_one_logit_per_horizon_step() -> None:
    model = GripperEventHead(action_horizon=4)
    output = model(
        torch.zeros(2, 8), torch.zeros(2, 3, 96, 128), torch.zeros(2, 3, 96, 128)
    )
    assert output.shape == (2, 4)


def test_image_tensor_accepts_hwc_uint8() -> None:
    result = _image_tensor(np.full((20, 30, 3), 255, dtype=np.uint8))
    assert result.shape == (3, 96, 128)
    assert torch.allclose(result, torch.ones_like(result))


def test_gripper_override_preserves_all_arm_actions() -> None:
    class Base:
        metadata = {"action_horizon": 4}

        def infer(self, obs, *, noise=None):
            del obs, noise
            return {"actions": np.arange(32, dtype=np.float32).reshape(4, 8)}

    head = GripperEventHead(action_horizon=4)
    for parameter in head.parameters():
        torch.nn.init.zeros_(parameter)
    policy = GripperOverridePolicy(Base(), head, device="cpu")
    observation = {
        "observation/state": np.zeros(8, dtype=np.float32),
        "observation/image": np.zeros((10, 12, 3), dtype=np.uint8),
        "observation/wrist_image": np.zeros((10, 12, 3), dtype=np.uint8),
    }
    result = policy.infer(observation)
    expected = np.arange(32, dtype=np.float32).reshape(4, 8)
    np.testing.assert_array_equal(result["actions"][:, :7], expected[:, :7])
    np.testing.assert_allclose(result["actions"][:, 7], 0.5)
