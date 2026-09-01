import numpy as np

from robot_data_studio.episode_contract import inspect_episode
from robot_data_studio.runtime.episode_writer import EpisodeWriter


def test_generic_writer_and_inspector_preserve_unavailable_automatic_outcome(tmp_path):
    writer = EpisodeWriter(
        tmp_path,
        fps=20,
        engine_id="isaac_sim",
        engine_version="test",
        scene_id="franka_empty",
        robot_id="franka_panda",
        control_source="gello",
        state_names=["q0", "dq0"],
        action_names=["target_q0"],
        camera_names=[],
        run_metadata={"gpu_id": 0},
    )
    writer.start("move safely")
    writer.add_frame(
        images={},
        state=np.asarray([0.0, 0.0]),
        action=np.asarray([0.1]),
        sim_time=0.0,
        control_sequence=4,
        control_timestamp_ns=10,
    )
    episode_path = writer.finish(operator_success=True)

    descriptor = inspect_episode(episode_path / "manifest.json", engine_id="isaac_sim")

    assert descriptor.num_frames == 1
    assert descriptor.operator_success is True
    assert descriptor.auto_success is None
    assert descriptor.manifest["automatic_outcome"] == "unavailable"
