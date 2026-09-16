from pathlib import Path

import pytest

from robot_data_studio.adapters.roboverse import RoboVerseAdapter
from robot_data_studio.config import CONTRACTS_SRC, PROJECT_ROOT, settings


def config(**updates):
    value = {
        "scene_id": "maniskill_pick_cube_native",
        "control_mode": "scripted",
        "target_episodes": 1,
        "gpu": 3,
        "control_fps": 20,
        "width": 640,
        "height": 480,
        "scene_params": {},
        "camera_profile_id": "roboverse_sapien_base_v1",
    }
    value.update(updates)
    return value


def test_roboverse_launch_is_isolated_and_allowlisted() -> None:
    adapter = RoboVerseAdapter()
    launch = adapter.build_worker_launch(config(), Path("/tmp/roboverse-data"))

    assert launch.command[:3] == [
        str(settings.roboverse_python),
        "-m",
        "robot_data_studio.workers.roboverse",
    ]
    assert launch.command[launch.command.index("--scene") + 1] == "maniskill_pick_cube_native"
    assert launch.command[launch.command.index("--episodes") + 1] == "1"
    assert launch.command[launch.command.index("--steps") + 1] == "50"
    assert launch.command[launch.command.index("--demo-file") + 1] == str(
        settings.roboverse_pickcube_demo
    )
    assert launch.cwd == settings.roboverse_root
    assert launch.env_updates["CUDA_VISIBLE_DEVICES"] == "3"
    python_path = launch.env_updates["PYTHONPATH"].split(":")
    assert str(PROJECT_ROOT / "backend" / "src") in python_path
    assert str(CONTRACTS_SRC) in python_path
    assert str(settings.roboverse_root / "packages" / "metasim") in python_path


def test_roboverse_descriptor_exposes_session_constraints() -> None:
    descriptor = RoboVerseAdapter().descriptor()

    assert descriptor["session_limits"]["target_episodes"] == {
        "minimum": 1,
        "maximum": 10,
        "default": 1,
    }
    assert descriptor["runtime"]["headless"] is True
    assert descriptor["runtime"]["uses_gpu"] is True
    assert descriptor["runtime"]["uses_collector_port"] is False


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"control_mode": "gello"}, "scripted control only"),
        ({"scene_id": "untrusted"}, "unsupported RoboVerse scene"),
        ({"target_episodes": 11}, "1 to 10"),
        ({"control_fps": 10}, "control_fps=20"),
        ({"scene_params": {"shell": 1}}, "not allowlisted"),
        ({"scene_params": {"episode_steps": 50}}, "not allowlisted"),
    ],
)
def test_roboverse_rejects_out_of_scope_configuration(updates, message) -> None:
    with pytest.raises(ValueError, match=message):
        RoboVerseAdapter().validate_config(config(**updates))
