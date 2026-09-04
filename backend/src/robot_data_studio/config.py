from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
CONTRACTS_SRC = PROJECT_ROOT / "packages" / "robot-data-contracts" / "src"


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv("ROBOT_DATA_STUDIO_DB", PROJECT_ROOT / "data" / "studio.db"))
    data_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_DATA_ROOT", PROJECT_ROOT / "data"))
    camera_profile_root: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_CAMERA_PROFILE_ROOT", PROJECT_ROOT / "config" / "camera_profiles")
    )
    clothtwin_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_CLOTHTWIN_ROOT", "/data/zhanghejun/ClothTwin"))
    collector_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_COLLECTOR_PYTHON", "/home/zhanghejun/miniconda3/envs/genesis/bin/python"
    )
    gello_remote_root: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT", "/data/zhanghejun/gello-remote")
    )
    isaaclab_launcher: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_ISAACLAB_LAUNCHER", "/data/zhanghejun/IsaacLab/isaaclab.sh")
    )
    isaaclab_conda_prefix: Path = Path(
        os.getenv(
            "ROBOT_DATA_STUDIO_ISAACLAB_CONDA_PREFIX",
            "/home/zhanghejun/miniconda3/envs/isaaclab",
        )
    )
    public_ip: str = os.getenv("ROBOT_DATA_STUDIO_PUBLIC_IP", "219.223.200.145")
    isaac_signaling_port: int = int(os.getenv("ROBOT_DATA_STUDIO_ISAAC_SIGNALING_PORT", "49100"))
    isaac_media_port: int = int(os.getenv("ROBOT_DATA_STUDIO_ISAAC_MEDIA_PORT", "47998"))
    isaac_franka_usd: str = os.getenv(
        "ROBOT_DATA_STUDIO_ISAAC_FRANKA_USD",
        "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd",
    )
    lerobot_python: str = os.getenv("ROBOT_DATA_STUDIO_LEROBOT_PYTHON", "python")
    openpi_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_OPENPI_ROOT", "/data/zhanghejun/openpi"))
    openpi_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_OPENPI_PYTHON", "/data/zhanghejun/openpi/.venv/bin/python"
    )
    openpi_checkpoint: Path = Path(
        os.getenv(
            "ROBOT_DATA_STUDIO_OPENPI_CHECKPOINT",
            "/data/zhanghejun/robot-data-studio/data/training/"
            "openpi_franka_joint8_seed0_train16_v1/checkpoints/"
            "pi05_franka_joint8_lora/seed0_train16_step2000_v1/1999",
        )
    )
    openpi_config: str = os.getenv(
        "ROBOT_DATA_STUDIO_OPENPI_CONFIG", "pi05_franka_joint8_lora"
    )
    openpi_gpu_id: int = int(os.getenv("ROBOT_DATA_STUDIO_OPENPI_GPU_ID", "7"))
    openpi_inference_steps: int = int(
        os.getenv("ROBOT_DATA_STUDIO_OPENPI_INFERENCE_STEPS", "2")
    )
    fastwam_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_FASTWAM_PYTHON",
        "/data/zhanghejun/envs/lerobot-fastwam/bin/python",
    )
    rlds_python: str = os.getenv("ROBOT_DATA_STUDIO_RLDS_PYTHON", "python")
    robomimic_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_ROBOMIMIC_PYTHON", "/home/zhanghejun/miniconda3/envs/softmimicgen/bin/python"
    )


settings = Settings()
