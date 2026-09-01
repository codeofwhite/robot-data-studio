from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ControlMode = Literal["keyboard", "gello"]
EngineId = Literal["genesis", "isaac_sim"]
QaStatus = Literal["pending", "accepted", "rejected"]
ExportFormat = Literal["lerobot", "rlds", "robomimic"]


class SessionCreate(BaseModel):
    engine_id: EngineId = "genesis"
    dataset_name: str = Field(min_length=1, max_length=80)
    scene_id: str = Field(min_length=1, max_length=100)
    control_mode: ControlMode
    target_episodes: int = Field(default=50, ge=1, le=10_000)
    port: int = Field(default=8080, ge=1024, le=65535)
    gpu: int = Field(default=0, ge=0, le=255)
    control_fps: int = Field(default=10, ge=1, le=120)
    physics_steps_per_control: int = Field(default=2, ge=1, le=64)
    width: int = Field(default=640, ge=64, le=4096)
    height: int = Field(default=480, ge=64, le=4096)
    camera_profile_id: str = Field(default="lab_d435i_dual_v1", pattern=r"^[a-z][a-z0-9_]*$")
    scene_params: dict[str, float | int] = Field(default_factory=dict)

    @field_validator("dataset_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        cleaned = value.strip()
        if any(part in cleaned for part in ("/", "\\", "..")):
            raise ValueError("dataset_name must be a simple name")
        return cleaned


class QaUpdate(BaseModel):
    qa_status: QaStatus
    failure_reason: str | None = Field(default=None, max_length=240)


class ExportCreate(BaseModel):
    dataset_id: int
    format: ExportFormat
    output_name: str = Field(min_length=1, max_length=100)
    repo_id: str | None = Field(default=None, max_length=200)
    images: bool = False

    @field_validator("output_name")
    @classmethod
    def safe_output_name(cls, value: str) -> str:
        cleaned = value.strip()
        if any(part in cleaned for part in ("/", "\\", "..")):
            raise ValueError("output_name must be a simple name")
        return cleaned


class ApiMessage(BaseModel):
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
