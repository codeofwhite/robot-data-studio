from pathlib import Path

import pytest

from robot_data_studio.adapters.clothtwin import ClothTwinAdapter
from robot_data_studio.adapters.isaac_sim import IsaacSimAdapter


def test_keyboard_and_gello_have_separate_allowlisted_modules():
    adapter = ClothTwinAdapter()
    base = {
        "scene_id": "rigid_pick_place", "port": 8080, "control_fps": 10,
        "physics_steps_per_control": 2, "width": 640, "height": 480, "scene_params": {},
        "camera_profile_id": "lab_d435i_dual_v1",
    }
    keyboard = adapter.build_collect_command({**base, "control_mode": "keyboard"}, Path("/tmp/data"))
    gello = adapter.build_collect_command({**base, "control_mode": "gello"}, Path("/tmp/data"))
    assert "franka_only.keyboard_collect" in keyboard
    assert "franka_only.gello_collect" in gello
    assert keyboard != gello
    assert keyboard[keyboard.index("--camera-profile-file") + 1].endswith("lab_d435i_dual_v1.json")


def test_rejects_unallowlisted_scene_parameter():
    adapter = ClothTwinAdapter()
    with pytest.raises(ValueError, match="not allowlisted"):
        adapter.build_collect_command({
            "scene_id": "cloth_corner_lift", "control_mode": "gello", "port": 8080,
            "control_fps": 10, "physics_steps_per_control": 2, "width": 640, "height": 480,
            "scene_params": {"dangerous_option": 1},
        }, Path("/tmp/data"))


def test_isaac_launch_uses_gpu_id_and_removes_cuda_visibility():
    adapter = IsaacSimAdapter()
    config = {
        "scene_id": "franka_empty",
        "control_mode": "gello",
        "gpu": 6,
        "port": 8080,
        "control_fps": 20,
        "width": 640,
        "height": 480,
        "scene_params": {},
        "camera_profile_id": "lab_d435i_dual_v1",
    }
    launch = adapter.build_worker_launch(config, Path("/tmp/isaac-data"))
    assert launch.command[launch.command.index("--gpu-id") + 1] == "6"
    assert launch.command[launch.command.index("--data-dir") + 1] == "/tmp/isaac-data"
    assert "CUDA_VISIBLE_DEVICES" in launch.unset_env
    assert "CUDA_VISIBLE_DEVICES" not in launch.env_updates
    assert launch.command[launch.command.index("--camera-profile-file") + 1].endswith("lab_d435i_dual_v1.json")
