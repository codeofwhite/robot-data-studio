from __future__ import annotations

from typing import Any
import math

import numpy as np

from .episode import AugmentationLineageV1, EvaluatorResultV1, SceneProvenanceV1
from .profiles.franka import FRANKA_JOINT8_ACTION, franka_feature_specs, policy_action_from_native, policy_state_from_native
from .provenance import collect_software_provenance
from .writer import EpisodeWriter


class FrankaEpisodeWriter:
    """Franka convenience facade over the engine-neutral EpisodeWriter."""

    def __init__(self, root, *, fps: int, engine_id: str, engine_version: str, scene_id: str,
                 control_source: str, operator_command_names: list[str], camera_names: list[str],
                 run_metadata: dict[str, Any], seed: int = 0, worker_id: str = "unknown",
                 state_names=None, action_names=None,
                 generation_method: str | None = None) -> None:
        camera_profile = run_metadata.get("camera_profile", {})
        camera_roles = run_metadata.get("camera_roles", {})
        intrinsics = run_metadata.get("camera_intrinsic_matrices", {})
        extrinsics = run_metadata.get("camera_extrinsics", {})
        resolved_cameras = (
            run_metadata.get("scene_geometry", {}).get("cameras", {})
            or run_metadata.get("resolved_scene_spec", {}).get("cameras", {})
        )
        width, height = (run_metadata.get("camera_resolution") or [None, None])[:2]
        profile_roles = camera_profile.get("roles", {})

        def intrinsic_for(name: str):
            if name in intrinsics:
                return intrinsics[name]
            role_name = "agentview" if name == "base" else name
            calibrated = profile_roles.get(role_name, {}).get("intrinsics")
            if calibrated:
                return calibrated
            fov = resolved_cameras.get(name, {}).get("vertical_fov_deg")
            if fov is None:
                fov = profile_roles.get(role_name, {}).get("nominal_vertical_fov_deg")
            if width and height and fov:
                focal = (float(height) / 2.0) / math.tan(math.radians(float(fov)) / 2.0)
                return [focal, 0.0, width / 2.0, 0.0, focal, height / 2.0, 0.0, 0.0, 1.0]
            return None

        calibration = {
            name: {"role": camera_roles.get(name), "profile": camera_profile.get("id"),
                   "intrinsics": intrinsic_for(name),
                   "extrinsics": extrinsics.get(name, resolved_cameras.get(name))}
            for name in camera_names
        }
        software = collect_software_provenance(
            engine_id=engine_id, engine_version=engine_version, worker_id=worker_id,
            git_roots=dict(run_metadata.get("git_roots", {})),
            packages=tuple(run_metadata.get("dependency_packages", ())),
        )
        scene_parameters = dict(run_metadata)
        for key in ("camera_profile", "camera_roles", "camera_intrinsic_matrices", "camera_extrinsics",
                    "git_roots", "dependency_packages", "assets"):
            scene_parameters.pop(key, None)
        assets = list(run_metadata.get("assets", []))
        if not assets and run_metadata.get("object_assets"):
            assets = [{"description": str(run_metadata["object_assets"])}]
        self._writer = EpisodeWriter(
            root, fps=fps, robot_id="franka_panda", control_source=control_source,
            features=franka_feature_specs(tuple(operator_command_names)), action_profile=FRANKA_JOINT8_ACTION,
            camera_names=tuple(camera_names), camera_calibration=calibration,
            scene=SceneProvenanceV1(scene_id=scene_id, seed=seed,
                                    parameters=scene_parameters,
                                    assets=assets),
            software=software,
            lineage=AugmentationLineageV1(
                generation_method=(
                    generation_method
                    if generation_method is not None
                    else ("scripted" if control_source.startswith("scripted") else "teleoperation")
                )
            ),
        )
        self.camera_names = list(camera_names)

    @property
    def is_recording(self): return self._writer.is_recording
    @property
    def frame_count(self): return self._writer.frame_count
    def start(self, task: str): return self._writer.start(task)
    def discard(self): return self._writer.discard()

    def add_frame(self, *, images, state, action, operator_command, sim_time,
                  requested_action=None, safe_action=None, applied_action=None,
                  control_timestamp_ns=-1, control_receive_timestamp_ns=-1,
                  capture_timestamp_ns=None, control_sequence=-1, extra_arrays=None,
                  ee_pose=None, target_ee_pose=None,
                  object_pose=None, object_velocity=None, cloth_particles=None,
                  cloth_particle_velocities=None, **_) -> None:
        safe_native = np.asarray(safe_action if safe_action is not None else action, dtype=np.float32)
        applied_native = np.asarray(applied_action if applied_action is not None else action, dtype=np.float32)
        requested_native = np.asarray(requested_action if requested_action is not None else safe_native, dtype=np.float32)
        auxiliary = dict(extra_arrays or {})
        for key, value in {
            "ee_pose": ee_pose, "target_ee_pose": target_ee_pose, "object_pose": object_pose,
            "object_velocity": object_velocity, "cloth_particles": cloth_particles,
            "cloth_particle_velocities": cloth_particle_velocities,
        }.items():
            if value is not None: auxiliary[key] = value
        values = {
            "native_state": np.asarray(state, np.float32),
            "policy_state": policy_state_from_native(state),
            "operator_action": np.asarray(operator_command, np.float32),
            "requested_action": policy_action_from_native(requested_native),
            "safe_action": policy_action_from_native(safe_native),
            "applied_action": policy_action_from_native(applied_native),
            **auxiliary,
        }
        self._writer.add_frame(images=images, values=values, simulation_time_s=sim_time,
                               control_source_timestamp_ns=control_timestamp_ns,
                               control_receive_timestamp_ns=control_receive_timestamp_ns,
                               capture_timestamp_ns=capture_timestamp_ns,
                               control_sequence=control_sequence)

    def finish(self, *, operator_success: bool, episode_metrics: dict[str, Any],
               auto_success: bool | None = None, evaluator_id: str = "task_evaluator",
               evaluator_version: str = "1"):
        available = auto_success is not None
        evaluator = EvaluatorResultV1(
            evaluator_id=evaluator_id, evaluator_version=evaluator_version, available=available,
            success=auto_success if available else None, metrics=episode_metrics,
            unavailable_reason=None if available else "task evaluator unavailable",
        )
        failure = (
            "operator_marked_failure" if operator_success is False
            else ("automatic_criterion_not_met" if auto_success is False else None)
        )
        return self._writer.finish(operator_success=operator_success, evaluator=evaluator, failure_reason=failure)
