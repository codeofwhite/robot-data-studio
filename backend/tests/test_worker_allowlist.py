from pathlib import Path

import pytest

from robot_data_studio.adapters.clothtwin import ClothTwinAdapter
from robot_data_studio.adapters.isaac_sim import IsaacSimAdapter
from robot_data_studio.config import CONTRACTS_SRC


def test_keyboard_and_gello_have_separate_allowlisted_modules():
    adapter = ClothTwinAdapter()
    base = {
        "scene_id": "rigid_pick_place", "port": 8080, "control_fps": 10,
        "sim_dt": 0.01, "physics_steps_per_control": 10,
        "width": 640, "height": 480, "scene_params": {},
        "camera_profile_id": "lab_d435i_dual_v1",
    }
    keyboard = adapter.build_collect_command({**base, "control_mode": "keyboard"}, Path("/tmp/data"))
    gello = adapter.build_collect_command({**base, "control_mode": "gello"}, Path("/tmp/data"))
    assert "gello_remote.genesis_worker" in keyboard
    assert "gello_remote.genesis_worker" in gello
    assert keyboard != gello
    assert keyboard[keyboard.index("--control-source") + 1] == "keyboard"
    assert gello[gello.index("--control-source") + 1] == "gello"
    assert keyboard[keyboard.index("--camera-profile-file") + 1].endswith("lab_d435i_dual_v1.json")
    assert keyboard[keyboard.index("--sim-dt") + 1] == "0.01"


def test_genesis_worker_is_launched_from_gello_remote():
    adapter = ClothTwinAdapter()
    config = {
        "scene_id": "rigid_pick_place", "control_mode": "gello", "gpu": 2,
        "port": 8080, "control_fps": 10, "sim_dt": 0.01,
        "physics_steps_per_control": 10,
        "width": 640, "height": 480, "scene_params": {},
        "camera_profile_id": "lab_d435i_dual_v1",
    }
    launch = adapter.build_worker_launch(config, Path("/tmp/data"))
    assert launch.cwd.name == "gello-remote"
    assert launch.env_updates["CUDA_VISIBLE_DEVICES"] == "2"
    assert "ClothTwin" in launch.env_updates["PYTHONPATH"]


def test_rejects_unallowlisted_scene_parameter():
    adapter = ClothTwinAdapter()
    with pytest.raises(ValueError, match="not allowlisted"):
        adapter.build_collect_command({
            "scene_id": "cloth_corner_lift", "control_mode": "gello", "port": 8080,
            "control_fps": 10, "sim_dt": 0.01, "physics_steps_per_control": 10,
            "width": 640, "height": 480,
            "scene_params": {"dangerous_option": 1},
        }, Path("/tmp/data"))


def test_genesis_rigid_scene_passes_work_surface_height() -> None:
    adapter = ClothTwinAdapter()
    config = {
        "scene_id": "rigid_pick_place",
        "control_mode": "gello",
        "port": 8080,
        "control_fps": 10,
        "sim_dt": 0.01,
        "physics_steps_per_control": 10,
        "width": 640,
        "height": 480,
        "scene_params": {"work_surface_height_m": 0.28},
        "camera_profile_id": "lab_d435i_dual_v1",
    }
    command = adapter.build_collect_command(config, Path("/tmp/data"))
    assert command[command.index("--scene-param") + 1] == "work_surface_height_m=0.28"


def test_genesis_rejects_mismatched_control_and_simulation_time() -> None:
    adapter = ClothTwinAdapter()
    config = {
        "scene_id": "rigid_pick_place",
        "control_mode": "keyboard",
        "port": 8080,
        "control_fps": 10,
        "sim_dt": 0.01,
        "physics_steps_per_control": 2,
        "width": 640,
        "height": 480,
        "scene_params": {},
        "camera_profile_id": "lab_d435i_dual_v1",
    }
    with pytest.raises(ValueError, match="inconsistent Genesis timing"):
        adapter.build_collect_command(config, Path("/tmp/data"))


def test_isaac_launch_uses_gpu_id_and_single_cuda_visibility():
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
    assert launch.command[launch.command.index("--control-source") + 1] == "gello"
    assert launch.env_updates["CUDA_VISIBLE_DEVICES"] == "6"
    assert "CUDA_VISIBLE_DEVICES" not in launch.unset_env
    assert str(CONTRACTS_SRC) in launch.env_updates["PYTHONPATH"].split(":")
    assert launch.command[launch.command.index("--camera-profile-file") + 1].endswith("lab_d435i_dual_v1.json")
    kit_args = launch.command[launch.command.index("--kit_args") + 1]
    assert "--/app/window/width=960" in kit_args
    assert "--/app/window/height=720" in kit_args


def test_isaac_keyboard_launch_is_allowlisted() -> None:
    adapter = IsaacSimAdapter()
    config = {
        "scene_id": "franka_empty",
        "control_mode": "keyboard",
        "gpu": 6,
        "port": 8080,
        "control_fps": 20,
        "width": 640,
        "height": 480,
        "scene_params": {},
        "camera_profile_id": "lab_d435i_dual_v1",
    }

    command = adapter.build_collect_command(config, Path("/tmp/isaac-keyboard-data"))

    assert command[command.index("--control-source") + 1] == "keyboard"
    assert command[command.index("--data-dir") + 1] == "/tmp/isaac-keyboard-data"


def test_isaac_rigid_scene_passes_work_surface_height() -> None:
    adapter = IsaacSimAdapter()
    config = {
        "scene_id": "rigid_pick_place",
        "control_mode": "gello",
        "gpu": 6,
        "port": 8080,
        "control_fps": 20,
        "width": 640,
        "height": 480,
        "scene_params": {"work_surface_height_m": 0.28},
        "camera_profile_id": "lab_d435i_dual_v1",
    }
    command = adapter.build_collect_command(config, Path("/tmp/isaac-data"))
    assert command[command.index("--scene") + 1] == "rigid_pick_place"
    assert command[command.index("--work-surface-height-m") + 1] == "0.28"

    with pytest.raises(ValueError, match="not allowlisted"):
        adapter.build_collect_command(
            {**config, "scene_params": {"unsupported": 1}}, Path("/tmp/isaac-data")
        )


def test_isaac_cube_lift_scene_is_registered_and_passes_height() -> None:
    adapter = IsaacSimAdapter()
    config = {
        "scene_id": "rigid_cube_lift",
        "control_mode": "keyboard",
        "gpu": 6,
        "port": 8080,
        "control_fps": 10,
        "width": 640,
        "height": 480,
        "scene_params": {"work_surface_height_m": 0.25},
        "camera_profile_id": "lab_d435i_dual_v1",
    }

    command = adapter.build_collect_command(config, Path("/tmp/isaac-cube-data"))

    assert adapter.scenes["rigid_cube_lift"]["family"] == "rigid_pick"
    assert adapter.scenes["rigid_cube_lift"]["automatic_outcome"] is True
    assert command[command.index("--scene") + 1] == "rigid_cube_lift"
    assert command[command.index("--work-surface-height-m") + 1] == "0.25"
