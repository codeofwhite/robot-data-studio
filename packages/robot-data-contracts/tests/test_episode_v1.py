import json
import sys

import numpy as np
from PIL import Image

from robot_data_contracts import (
    TRAINING_PROFILES,
    AugmentationLineageV1,
    EpisodeWriter,
    EvaluatorResultV1,
    FrankaEpisodeWriter,
    SceneProvenanceV1,
    SoftwareProvenanceV1,
    WorkerDescriptorV1,
    adapt_franka_joint8,
    inspect_episode,
    iter_training_frames,
    open_canonical_episode,
)
from robot_data_contracts.profiles.franka import FRANKA_JOINT8_ACTION, franka_feature_specs


def test_episode_writer_falls_back_to_pillow_without_opencv(tmp_path, monkeypatch) -> None:
    writer = object.__new__(EpisodeWriter)
    writer.jpeg_quality = 95
    path = tmp_path / "frame.jpg"
    image = np.zeros((3, 4, 3), dtype=np.uint8)
    image[..., 0] = 255
    monkeypatch.setitem(sys.modules, "cv2", None)

    writer._write_rgb(path, image)

    with Image.open(path) as encoded:
        assert encoded.size == (4, 3)
        assert encoded.mode == "RGB"


def test_franka_writer_accepts_empty_optional_scene_metadata(tmp_path) -> None:
    writer = FrankaEpisodeWriter(
        tmp_path,
        fps=10,
        engine_id="isaac_sim",
        engine_version="test",
        scene_id="franka_empty",
        control_source="browser_se3_keyboard",
        operator_command_names=[
            "dx_m",
            "dy_m",
            "dz_m",
            "droll_rad",
            "dpitch_rad",
            "dyaw_rad",
            "gripper_closed",
        ],
        camera_names=[],
        run_metadata={"scene_geometry": None, "resolved_scene_spec": None},
    )

    assert writer.is_recording is False


def test_franka_writer_preserves_renderer_profile_provenance(tmp_path) -> None:
    renderer = {
        "id": "isaac_quality_v1", "profile_version": 1, "rendering_mode": "quality",
        "profile_sha256": "a" * 64, "kit_settings": {"/UJITSO/geometry": False},
    }
    writer = FrankaEpisodeWriter(
        tmp_path, fps=10, engine_id="isaac_sim", engine_version="test",
        scene_id="rigid_cube_lift", control_source="browser_se3_keyboard",
        operator_command_names=["gripper_closed"], camera_names=[],
        run_metadata={"renderer_profile": renderer},
    )
    assert writer._writer.scene.parameters["renderer_profile"] == renderer


def test_episode_v1_contains_required_action_stages_and_timestamps(tmp_path) -> None:
    writer = EpisodeWriter(
        tmp_path, fps=20, robot_id="franka_panda", control_source="gello_joint_targets",
        features=franka_feature_specs(), action_profile=FRANKA_JOINT8_ACTION,
        camera_names=(), camera_calibration={},
        scene=SceneProvenanceV1(scene_id="rigid_pick_place", seed=7),
        software=SoftwareProvenanceV1(
            python_version="test", platform="test", engine_id="genesis",
            engine_version="test", worker_id="genesis_worker",
        ),
        lineage=AugmentationLineageV1(generation_method="teleoperation"),
    )
    writer.start("pick the object")
    writer.add_frame(
        images={}, simulation_time_s=0.0, control_source_timestamp_ns=100,
        control_receive_timestamp_ns=110, capture_timestamp_ns=120, control_sequence=3,
        values={
            "native_state": np.zeros(18, np.float32),
            "policy_state": np.zeros(16, np.float32),
            "operator_action": np.zeros(7, np.float32),
            "requested_action": np.zeros(8, np.float32),
            "safe_action": np.zeros(8, np.float32),
            "applied_action": np.zeros(8, np.float32),
        },
    )
    episode = writer.finish(
        operator_success=True,
        evaluator=EvaluatorResultV1(
            evaluator_id="pick_v1", evaluator_version="1", available=True,
            success=True, metrics={"hold_frames": 5},
        ),
    )

    descriptor = inspect_episode(episode / "manifest.json")
    with np.load(episode / "trajectory.npz") as arrays:
        assert arrays["control_sequence"].tolist() == [3]
        assert arrays["control_source_timestamp_ns"].tolist() == [100]
        assert arrays["control_receive_timestamp_ns"].tolist() == [110]
        assert arrays["capture_timestamp_ns"].tolist() == [120]
    assert descriptor.auto_success is True
    assert json.loads((episode / "manifest.json").read_text())["scene"]["seed"] == 7


def test_training_profiles_are_explicit_and_do_not_mutate_physical_values() -> None:
    state = np.asarray([0.0] * 7 + [0.08] + [0.0] * 8, dtype=np.float32)
    action = np.asarray([0.0] * 7 + [0.0], dtype=np.float32)
    openpi_state, openpi_action = adapt_franka_joint8(state, action, "openpi_franka_joint8")
    fastwam_state, fastwam_action = adapt_franka_joint8(state, action, "fastwam_franka_joint8")
    assert openpi_state.shape == openpi_action.shape == (8,)
    assert openpi_state[7] == 0.0 and openpi_action[7] == 1.0
    assert fastwam_state[7] == 0.08 and fastwam_action[7] == 0.0
    assert TRAINING_PROFILES["fastwam_franka_joint8"].action_dimension == 8


def test_worker_descriptor_v1_round_trip() -> None:
    descriptor = WorkerDescriptorV1(
        worker_id="gello_remote_genesis", engine_id="genesis",
        entrypoint="gello_remote.genesis_worker", control_modes=("keyboard", "gello"),
        capabilities={"recording": True, "automatic_outcome": True},
    )
    assert descriptor.contract_version == 1


def test_policy_rollout_lineage_is_explicit() -> None:
    lineage = AugmentationLineageV1(generation_method="policy_rollout")
    assert lineage.generation_method == "policy_rollout"


def test_franka_writer_accepts_complete_augmentation_lineage(tmp_path) -> None:
    lineage = AugmentationLineageV1(
        parent_episode_uuid="source-uuid",
        generation_method="retargeted",
        randomization_spec_id="isaac_rigid_cube_lift_xy_v1",
        randomization_seed=17,
        resolved_parameters={"object_xy_offset_m": [0.01, -0.02]},
        trajectory_modified=True,
    )
    writer = FrankaEpisodeWriter(
        tmp_path,
        fps=10,
        engine_id="isaac_sim",
        engine_version="test",
        scene_id="rigid_cube_lift",
        control_source="retargeted_trajectory",
        operator_command_names=[
            "target_x_m", "target_y_m", "target_z_m", "target_qw",
            "target_qx", "target_qy", "target_qz", "gripper_closed",
        ],
        camera_names=[],
        run_metadata={"scene_geometry": None, "resolved_scene_spec": None},
        lineage=lineage,
    )

    assert writer._writer.lineage == lineage


def test_franka_writer_rejects_ambiguous_lineage_inputs(tmp_path) -> None:
    with np.testing.assert_raises_regex(ValueError, "either lineage or generation_method"):
        FrankaEpisodeWriter(
            tmp_path,
            fps=10,
            engine_id="isaac_sim",
            engine_version="test",
            scene_id="rigid_cube_lift",
            control_source="retargeted_trajectory",
            operator_command_names=["gripper_closed"],
            camera_names=[],
            run_metadata={"scene_geometry": None, "resolved_scene_spec": None},
            generation_method="retargeted",
            lineage=AugmentationLineageV1(generation_method="retargeted"),
        )


def test_canonical_reader_exposes_paths_and_training_view(tmp_path) -> None:
    writer = EpisodeWriter(
        tmp_path, fps=10, robot_id="franka_panda", control_source="keyboard_cartesian",
        features=franka_feature_specs(), action_profile=FRANKA_JOINT8_ACTION,
        camera_names=(), camera_calibration={},
        scene=SceneProvenanceV1(scene_id="rigid_pick_place", seed=0),
        software=SoftwareProvenanceV1(
            python_version="test", platform="test", engine_id="genesis",
            engine_version="test", worker_id="genesis_worker",
        ),
        lineage=AugmentationLineageV1(generation_method="teleoperation"),
    )
    writer.start("pick the cube")
    policy_state = np.asarray([0.0] * 7 + [0.08] + [0.0] * 8, dtype=np.float32)
    applied_action = np.asarray([0.0] * 7 + [0.0], dtype=np.float32)
    writer.add_frame(
        images={}, simulation_time_s=0.0, control_source_timestamp_ns=100,
        control_receive_timestamp_ns=110, capture_timestamp_ns=120, control_sequence=0,
        values={
            "native_state": np.zeros(18, np.float32), "policy_state": policy_state,
            "operator_action": np.zeros(7, np.float32), "requested_action": applied_action,
            "safe_action": applied_action, "applied_action": applied_action,
        },
    )
    episode_path = writer.finish(
        operator_success=True,
        evaluator=EvaluatorResultV1(
            evaluator_id="pick_v1", evaluator_version="1", available=True, success=True,
        )
    )

    episode = open_canonical_episode(episode_path)
    frame = next(iter_training_frames(episode, "openpi_franka_joint8"))
    assert episode.length == 1
    assert frame["task"] == "pick the cube"
    assert frame["state"].shape == frame["action"].shape == (8,)
    assert frame["state"][7] == 0.0
    assert frame["action"][7] == 1.0
    selected = open_canonical_episode(
        episode_path, array_keys={"policy_state", "applied_action"}
    )
    assert set(selected.arrays) == {"policy_state", "applied_action"}
