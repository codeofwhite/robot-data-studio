from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import CONTRACTS_SRC, settings
from ..camera_profiles import validate_session_camera_profile
from .base import CollectionAdapter, WorkerLaunch


SCENES = {
    "franka_empty": {
        "label": "Franka 空场景遥操采集",
        "description": "Isaac Lab Franka 空场景采集。",
        "family": "general",
        "parameters": [],
    },
    "rigid_pick_place": {
        "label": "刚体抓取放置",
        "description": "Isaac Lab 刚体抓取放置场景。",
        "family": "general",
        "parameters": [
            {
                "key": "work_surface_height_m",
                "label": "工作面相对底座高度",
                "unit": "m",
                "minimum": 0.18,
                "maximum": 0.32,
                "step": 0.01,
                "default": 0.25,
                "scale": "linear",
            }
        ],
    },
}


class IsaacSimAdapter(CollectionAdapter):
    adapter_id = "isaac_sim"
    label = "Isaac Sim / Isaac Lab"
    scenes = SCENES
    control_modes = ("keyboard", "gello")
    camera_profile_ids = ("lab_d435i_dual_v1",)
    capabilities = {
        "webrtc": True,
        "recording": True,
        "automatic_outcome": False,
        "scene_reconfigure": False,
    }
    worker_entrypoint = "gello_remote.isaaclab_gello"

    def validate_config(self, config: dict[str, Any]) -> None:
        if config.get("control_mode") not in self.control_modes:
            raise ValueError("Isaac Sim supports keyboard or GELLO control only")
        if config.get("scene_id") not in self.scenes:
            raise ValueError("unsupported Isaac Sim scene")
        allowed_params = {
            item["key"] for item in self.scenes[config["scene_id"]]["parameters"]
        }
        unknown_params = sorted(set(config.get("scene_params", {})) - allowed_params)
        if unknown_params:
            raise ValueError(
                f"Isaac Sim scene parameter is not allowlisted: {', '.join(unknown_params)}"
            )
        profile_id = str(config.get("camera_profile_id", "lab_d435i_dual_v1"))
        if profile_id not in self.camera_profile_ids:
            raise ValueError(f"unsupported Isaac Sim camera profile: {profile_id}")
        validate_session_camera_profile(profile_id, width=int(config["width"]), height=int(config["height"]))

    def build_collect_command(self, config: dict[str, Any], output_dir: Path) -> list[str]:
        self.validate_config(config)
        command = [
            str(settings.isaaclab_launcher),
            "-p",
            "-m",
            "gello_remote.isaaclab_gello",
            "--control-source",
            str(config["control_mode"]),
            "--gpu-id",
            str(config["gpu"]),
            "--enable_cameras",
            "--livestream",
            "1",
            "--rendering_mode",
            "balanced",
            "--host",
            "127.0.0.1",
            "--port",
            str(config["port"]),
            "--stream-host",
            settings.public_ip,
            "--signaling-port",
            str(settings.isaac_signaling_port),
            "--media-port",
            str(settings.isaac_media_port),
            "--control_hz",
            str(config["control_fps"]),
            "--data-dir",
            str(output_dir),
            "--scene",
            config["scene_id"],
            "--width",
            str(config["width"]),
            "--height",
            str(config["height"]),
            "--camera-profile-file",
            str(validate_session_camera_profile(
                str(config.get("camera_profile_id", "lab_d435i_dual_v1")),
                width=int(config["width"]),
                height=int(config["height"]),
            )),
            "--franka-usd",
            settings.isaac_franka_usd,
            "--kit_args",
            "--/UJITSO/geometry=false --/persistent/UJITSO/geometry=false "
            "--/app/window/width=960 --/app/window/height=720",
        ]
        if config["scene_id"] == "rigid_pick_place":
            height = config.get("scene_params", {}).get("work_surface_height_m", 0.25)
            command += ["--work-surface-height-m", str(height)]
        return command

    def build_worker_launch(self, config: dict[str, Any], output_dir: Path) -> WorkerLaunch:
        python_paths = [
            str(settings.gello_remote_root / "src"),
            str(CONTRACTS_SRC),
        ]
        if os.environ.get("PYTHONPATH"):
            python_paths.append(os.environ["PYTHONPATH"])
        return WorkerLaunch(
            command=self.build_collect_command(config, output_dir),
            cwd=settings.gello_remote_root,
            env_updates={
                "CONDA_PREFIX": str(settings.isaaclab_conda_prefix),
                "CUDA_VISIBLE_DEVICES": str(config["gpu"]),
                "PYTHONPATH": ":".join(python_paths),
            },
        )
