from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..camera_profiles import validate_session_camera_profile
from ..config import CONTRACTS_SRC, PROJECT_ROOT, settings
from .base import CollectionAdapter, WorkerLaunch, WorkerReadiness


SCENES = {
    "maniskill_pick_cube_native": {
        "label": "ManiSkill PickCube Native",
        "description": (
            "RoboVerse MetaSim 的 ManiSkill Panda PickCube 原生任务；"
            "使用官方 ManiSkill pd_joint_delta_pos demonstration 验证采集、QA 与导出链路。"
        ),
        "family": "rigid_pick",
        "automatic_outcome": True,
        "parameters": [],
    }
}


class RoboVerseAdapter(CollectionAdapter):
    adapter_id = "roboverse"
    label = "RoboVerse / MetaSim"
    min_episodes = 1
    max_episodes = 10
    scenes = SCENES
    control_modes = ("scripted",)
    camera_profile_ids = ("roboverse_sapien_base_v1",)
    capabilities = {
        "webrtc": False,
        "recording": True,
        "automatic_outcome": True,
        "scene_reconfigure": False,
        "batch_generation": True,
        "interactive_ui": False,
    }
    worker_entrypoint = "robot_data_studio.workers.roboverse"

    def descriptor(self) -> dict[str, Any]:
        descriptor = super().descriptor()
        descriptor["worker"]["worker_id"] = "roboverse_maniskill_worker"
        descriptor["session_limits"] = {
            "target_episodes": {
                "minimum": self.min_episodes,
                "maximum": self.max_episodes,
                "default": 1,
            }
        }
        descriptor["runtime"] = {
            "headless": True,
            "uses_gpu": True,
            "uses_collector_port": False,
        }
        return descriptor

    def validate_config(self, config: dict[str, Any]) -> None:
        if config.get("control_mode") != "scripted":
            raise ValueError("RoboVerse P0 supports scripted control only")
        if config.get("scene_id") not in self.scenes:
            raise ValueError("unsupported RoboVerse scene")
        target_episodes = int(config.get("target_episodes", 0))
        if not self.min_episodes <= target_episodes <= self.max_episodes:
            raise ValueError("RoboVerse P0 supports 1 to 10 episodes per session")
        allowed_params = {
            item["key"] for item in self.scenes[config["scene_id"]]["parameters"]
        }
        unknown = sorted(set(config.get("scene_params", {})) - allowed_params)
        if unknown:
            raise ValueError(
                "RoboVerse scene parameter is not allowlisted: " + ", ".join(unknown)
            )
        if int(config.get("control_fps", 20)) != 20:
            raise ValueError("RoboVerse ManiSkill native task requires control_fps=20")
        profile_id = str(config.get("camera_profile_id", "roboverse_sapien_base_v1"))
        if profile_id not in self.camera_profile_ids:
            raise ValueError(f"unsupported RoboVerse camera profile: {profile_id}")
        validate_session_camera_profile(
            profile_id, width=int(config["width"]), height=int(config["height"])
        )

    def build_collect_command(self, config: dict[str, Any], output_dir: Path) -> list[str]:
        self.validate_config(config)
        return [
            str(settings.roboverse_python),
            "-m",
            self.worker_entrypoint,
            "--scene",
            str(config["scene_id"]),
            "--data-dir",
            str(output_dir),
            "--episodes",
            str(config["target_episodes"]),
            "--steps",
            "50",
            "--fps",
            str(config["control_fps"]),
            "--width",
            str(config["width"]),
            "--height",
            str(config["height"]),
            "--seed",
            "0",
            "--demo-file",
            str(settings.roboverse_pickcube_demo),
            "--camera-profile-file",
            str(
                validate_session_camera_profile(
                    str(config.get("camera_profile_id", "roboverse_sapien_base_v1")),
                    width=int(config["width"]),
                    height=int(config["height"]),
                )
            ),
        ]

    def build_worker_launch(self, config: dict[str, Any], output_dir: Path) -> WorkerLaunch:
        python_paths = [
            str(PROJECT_ROOT / "backend" / "src"),
            str(CONTRACTS_SRC),
            str(settings.roboverse_root),
            str(settings.roboverse_root / "packages" / "metasim"),
        ]
        if os.environ.get("PYTHONPATH"):
            python_paths.append(os.environ["PYTHONPATH"])
        return WorkerLaunch(
            command=self.build_collect_command(config, output_dir),
            cwd=settings.roboverse_root,
            env_updates={
                "CUDA_VISIBLE_DEVICES": str(config["gpu"]),
                "PYTHONPATH": os.pathsep.join(python_paths),
                "PYTHONDONTWRITEBYTECODE": "1",
                "SAPIEN_HEADLESS": "1",
            },
            readiness=WorkerReadiness(kind="marker", timeout_s=180.0),
            resources=(
                "simulator:global",
                f"gpu:{int(config['gpu'])}",
                f"output:{output_dir.resolve()}",
            ),
        )
