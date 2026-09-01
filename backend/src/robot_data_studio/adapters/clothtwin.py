from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import settings
from ..camera_profiles import validate_session_camera_profile
from .base import CollectionAdapter, WorkerLaunch


SCENES = {
    "rigid_pick_place": {"label": "刚体抓取放置", "family": "general", "params": []},
    "push_to_zone": {"label": "推到目标区", "family": "general", "params": []},
    "place_in_bin": {"label": "放入容器", "family": "general", "params": []},
    "cloth_corner_lift": {
        "label": "布料角点抓取抬升",
        "family": "cloth",
        "params": [
            {"key": "cloth_static_friction", "label": "静摩擦", "min": 0, "max": 2, "step": 0.05, "default": 0.4},
            {"key": "cloth_kinetic_friction", "label": "动摩擦", "min": 0, "max": 2, "step": 0.05, "default": 0.3},
            {"key": "cloth_stretch_compliance", "label": "拉伸柔顺度", "min": 1e-9, "max": 1e-4, "default": 1e-7},
            {"key": "cloth_bending_compliance", "label": "弯曲柔顺度", "min": 1e-8, "max": 1e-2, "default": 1e-5},
            {"key": "cloth_scale", "label": "布料尺寸", "min": 0.3, "max": 0.85, "step": 0.01, "default": 0.55},
            {"key": "required_corner_lift_m", "label": "成功抬升高度", "min": 0.05, "max": 0.4, "step": 0.01, "default": 0.15},
            {"key": "required_hold_frames", "label": "成功保持帧数", "min": 1, "max": 100, "step": 1, "default": 5},
        ],
    },
}
SAFE_PARAM = re.compile(r"^[a-z][a-z0-9_]*$")


class ClothTwinAdapter(CollectionAdapter):
    adapter_id = "genesis"
    label = "Genesis / ClothTwin"
    scenes = SCENES
    control_modes = ("keyboard", "gello")
    camera_profile_ids = ("lab_d435i_dual_v1",)
    capabilities = {
        "webrtc": False,
        "recording": True,
        "automatic_outcome": True,
        "scene_reconfigure": True,
    }
    allowed_modules = {
        "keyboard": "franka_only.keyboard_collect",
        "gello": "franka_only.gello_collect",
    }

    def validate_config(self, config: dict[str, Any]) -> None:
        mode = config["control_mode"]
        scene = config["scene_id"]
        if mode not in self.allowed_modules or scene not in SCENES:
            raise ValueError("unsupported ClothTwin collection mode or scene")
        allowed_params = {item["key"] for item in SCENES[scene]["params"]}
        for key in config.get("scene_params", {}):
            if key not in allowed_params or not SAFE_PARAM.fullmatch(key):
                raise ValueError(f"scene parameter is not allowlisted: {key}")
        profile_id = str(config.get("camera_profile_id", "lab_d435i_dual_v1"))
        if profile_id not in self.camera_profile_ids:
            raise ValueError(f"unsupported Genesis camera profile: {profile_id}")
        validate_session_camera_profile(profile_id, width=int(config["width"]), height=int(config["height"]))

    def build_collect_command(self, config: dict[str, Any], output_dir: Path) -> list[str]:
        self.validate_config(config)
        mode = config["control_mode"]
        scene = config["scene_id"]
        command = [
            settings.collector_python, "-m", self.allowed_modules[mode],
            "--scene", scene,
            "--host", "0.0.0.0",
            "--port", str(config["port"]),
            "--data-dir", str(output_dir),
            "--control-fps", str(config["control_fps"]),
            "--physics-steps-per-control", str(config["physics_steps_per_control"]),
            "--width", str(config["width"]),
            "--height", str(config["height"]),
            "--camera-profile-file",
            str(validate_session_camera_profile(
                str(config.get("camera_profile_id", "lab_d435i_dual_v1")),
                width=int(config["width"]),
                height=int(config["height"]),
            )),
        ]
        for key, value in sorted(config.get("scene_params", {}).items()):
            command += ["--scene-param", f"{key}={value}"]
        return command

    def build_worker_launch(self, config: dict[str, Any], output_dir: Path) -> WorkerLaunch:
        return WorkerLaunch(
            command=self.build_collect_command(config, output_dir),
            cwd=settings.clothtwin_root,
            env_updates={"CUDA_VISIBLE_DEVICES": str(config["gpu"])},
        )

    def build_export_command(self, format_name: str, input_root: Path, output: Path, **kwargs: Any) -> list[str]:
        if format_name not in {"lerobot", "rlds", "robomimic"}:
            raise ValueError("unsupported export format")
        interpreter = {
            "lerobot": settings.lerobot_python,
            "rlds": settings.rlds_python,
            "robomimic": settings.robomimic_python,
        }[format_name]
        command = [interpreter, "-m", "tools.export_dataset", "--format", format_name, "--input-root", str(input_root), "--output", str(output)]
        if kwargs.get("repo_id"):
            command += ["--repo-id", str(kwargs["repo_id"])]
        if kwargs.get("images"):
            command.append("--images")
        return command
