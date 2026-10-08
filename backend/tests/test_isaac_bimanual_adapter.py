from pathlib import Path
import pytest
from robot_data_studio.adapters.isaac_sim import IsaacSimAdapter


def config(**updates):
    return dict(scene_id="bimanual_tabletop_v17", control_mode="keyboard", gpu=2,
                port=18082, control_fps=20, width=960, height=720, scene_params={},
                camera_profile_id="isaac_bimanual_tabletop_visual_v4",
                renderer_profile_id="isaac_balanced_v1", physics_backend="physx", **updates)


def test_live_bimanual_launch_reuses_v17_assets_without_visual_capture():
    command = IsaacSimAdapter().build_collect_command(config(), Path("/tmp/bimanual-test"))
    for flag, suffix in (("--workstation-usd", "bimanual_tabletop_lab_v17.usda"),
                         ("--workstation-manifest-file", "asset_manifest_bimanual_v17.json"),
                         ("--franka-usd", "assets/franka/franka.usd")):
        assert command[command.index(flag) + 1].endswith(suffix)
    assert command[command.index("--scene") + 1] == "bimanual_tabletop_v17"
    assert "--visual-demo-output" not in command
    assert command[command.index("--width") + 1] == "960"


@pytest.mark.parametrize("key,value", [("control_mode", "gello"), ("physics_backend", "newton"),
                                       ("camera_profile_id", "lab_d435i_dual_v1"), ("width", 640)])
def test_rejects_incompatible_bimanual_launch(key, value):
    candidate = config()
    candidate[key] = value
    with pytest.raises(ValueError):
        IsaacSimAdapter().validate_config(candidate)
