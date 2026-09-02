from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..camera_profiles import camera_profile_descriptors


@dataclass(frozen=True)
class WorkerLaunch:
    command: list[str]
    cwd: Path
    env_updates: dict[str, str] = field(default_factory=dict)
    unset_env: tuple[str, ...] = ()


class CollectionAdapter(ABC):
    adapter_id: str
    label: str
    capabilities: dict[str, bool]
    scenes: dict[str, dict[str, Any]]
    control_modes: tuple[str, ...]
    camera_profile_ids: tuple[str, ...]

    def descriptor(self) -> dict[str, Any]:
        return {
            "id": self.adapter_id,
            "label": self.label,
            "capabilities": self.capabilities,
            "control_modes": list(self.control_modes),
            "scenes": self.scene_descriptors(),
            "camera_profiles": camera_profile_descriptors(self.camera_profile_ids),
        }

    def scene_descriptors(self) -> dict[str, dict[str, Any]]:
        return self.scenes

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def build_collect_command(self, config: dict[str, Any], output_dir: Path) -> list[str]: ...

    @abstractmethod
    def build_worker_launch(self, config: dict[str, Any], output_dir: Path) -> WorkerLaunch: ...

    @abstractmethod
    def build_export_command(self, format_name: str, input_root: Path, output: Path, **kwargs: Any) -> list[str]: ...
