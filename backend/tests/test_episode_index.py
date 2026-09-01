import json

import numpy as np

from robot_data_studio.models import SessionCreate
from robot_data_studio.services.episode_scanner import episode_detail, list_episodes, scan_session, update_qa
from robot_data_studio.services.session_service import create_session


def test_scan_detail_and_qa_keep_outcomes_separate(isolated_settings):
    session = create_session(SessionCreate(dataset_name="pilot", scene_id="cloth_corner_lift", control_mode="gello"))
    root = isolated_settings.data_root / "datasets" / "pilot" / "raw" / session["id"] / "episode_000000"
    root.mkdir()
    manifest = {
        "episode_uuid": "stable-uuid", "task": "lift corner", "num_frames": 3,
        "operator_success": True, "auto_success": False, "failure_reason": "automatic_criterion_not_met",
        "camera_names": ["front"], "fps": 10, "created_at": "2026-08-30T00:00:00+00:00",
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "front_rgb").mkdir()
    for index in range(3):
        (root / "front_rgb" / f"{index:06d}.jpg").write_bytes(b"jpeg")
    np.savez_compressed(
        root / "trajectory.npz",
        state=np.zeros((3, 18)),
        actions=np.zeros((3, 9)),
        frame_index=np.arange(3),
        timestamp=np.arange(3) / 10,
        sim_time=np.arange(3) / 10,
        policy_state=np.zeros((3, 8)),
        policy_action=np.ones((3, 8)),
        reward=np.zeros(3),
    )
    assert scan_session(session["id"]) == {"indexed": 1, "skipped": 0, "invalid": 0}
    episode = list_episodes()[0]
    assert episode["operator_success"] == 1
    assert episode["auto_success"] == 0
    assert episode["qa_status"] == "pending"
    update_qa(episode["id"], "accepted", "human override after replay")
    detail = episode_detail(episode["id"])
    assert detail["qa_status"] == "accepted"
    assert detail["operator_success"] == 1 and detail["auto_success"] == 0
    assert len(detail["trajectory"]["policy_action"]) == 3
