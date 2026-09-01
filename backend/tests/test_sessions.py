import pytest

from robot_data_studio.models import SessionCreate
from robot_data_studio.services.session_service import create_session, get_session


def test_create_and_get_session(isolated_settings):
    payload = SessionCreate(
        dataset_name="pilot", scene_id="cloth_corner_lift", control_mode="gello",
        target_episodes=20, port=8084, gpu=1,
    )
    session = create_session(payload)
    assert session["status"] == "draft"
    assert session["engine_id"] == "genesis"
    assert session["config"]["control_mode"] == "gello"
    assert session["config"]["camera_profile_id"] == "lab_d435i_dual_v1"
    detail = get_session(session["id"])
    assert detail["episode_count"] == 0
    assert detail["collector_url"] == "http://127.0.0.1:8084"


def test_rejects_unsafe_dataset_name(isolated_settings):
    with pytest.raises(ValueError, match="simple name"):
        SessionCreate(dataset_name="../escape", scene_id="rigid_pick_place", control_mode="keyboard")


def test_isaac_session_persists_engine_and_rejects_unsupported_control(isolated_settings):
    payload = SessionCreate(
        engine_id="isaac_sim",
        dataset_name="isaac_pilot",
        scene_id="franka_empty",
        control_mode="gello",
    )
    session = create_session(payload)
    assert session["engine_id"] == "isaac_sim"
    assert session["adapter_id"] == "isaac_sim"

    with pytest.raises(ValueError, match="GELLO"):
        create_session(
            SessionCreate(
                engine_id="isaac_sim",
                dataset_name="bad_isaac",
                scene_id="franka_empty",
                control_mode="keyboard",
            )
        )
