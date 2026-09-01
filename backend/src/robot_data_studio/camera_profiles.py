from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .config import settings


SAFE_PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
REQUIRED_ROLES = ("agentview", "wrist")
MATCH_LEVELS = {"nominal_pending_intrinsics", "intrinsics_matched", "sensor_matched"}


def camera_profile_path(profile_id: str) -> Path:
    if not SAFE_PROFILE_ID.fullmatch(profile_id):
        raise ValueError("camera profile id must be a simple lowercase identifier")
    path = (settings.camera_profile_root / f"{profile_id}.json").resolve()
    if not path.is_relative_to(settings.camera_profile_root.resolve()):
        raise ValueError("camera profile path escapes profile root")
    if not path.is_file():
        raise ValueError(f"unknown camera profile: {profile_id}")
    return path


def load_camera_profile(profile_id: str) -> dict[str, Any]:
    path = camera_profile_path(profile_id)
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("format") != "robot_data_studio_camera_profile" or profile.get("format_version") != 1:
        raise ValueError(f"unsupported camera profile format: {path}")
    if profile.get("id") != profile_id:
        raise ValueError(f"camera profile id does not match filename: {path}")
    if profile.get("match_level") not in MATCH_LEVELS:
        raise ValueError(f"invalid camera match level: {profile.get('match_level')}")
    roles = profile.get("roles")
    if not isinstance(roles, dict) or any(role not in roles for role in REQUIRED_ROLES):
        raise ValueError("camera profile must define agentview and wrist roles")
    for role in REQUIRED_ROLES:
        entry = roles[role]
        stream = entry.get("stream", {})
        if not entry.get("enabled") or not entry.get("model") or not entry.get("calibration_source_serial"):
            raise ValueError(f"camera role {role} is incomplete")
        if min(int(stream.get(key, 0)) for key in ("width", "height", "source_fps")) <= 0:
            raise ValueError(f"camera role {role} has invalid stream dimensions")
        intrinsics = entry.get("intrinsics")
        if profile["match_level"] != "nominal_pending_intrinsics" and not _valid_intrinsics(intrinsics):
            raise ValueError(f"camera role {role} requires calibrated intrinsics")
        if intrinsics is None and float(entry.get("nominal_vertical_fov_deg", 0.0)) <= 0:
            raise ValueError(f"camera role {role} requires a nominal vertical field of view")
    return profile


def camera_profile_descriptors(profile_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "id": profile["id"],
            "label": profile["label"],
            "match_level": profile["match_level"],
            "roles": [role for role, entry in profile["roles"].items() if entry.get("enabled")],
        }
        for profile in (load_camera_profile(profile_id) for profile_id in profile_ids)
    ]


def validate_session_camera_profile(profile_id: str, *, width: int, height: int) -> Path:
    profile = load_camera_profile(profile_id)
    expected = {
        (int(entry["stream"]["width"]), int(entry["stream"]["height"]))
        for entry in profile["roles"].values()
        if entry.get("enabled")
    }
    if expected != {(width, height)}:
        raise ValueError(
            f"camera profile {profile_id} requires one shared resolution {sorted(expected)}, got {(width, height)}"
        )
    return camera_profile_path(profile_id)


def _valid_intrinsics(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        return all(float(value[key]) > 0 for key in ("fx", "fy")) and all(
            float(value[key]) >= 0 for key in ("cx", "cy")
        )
    except (KeyError, TypeError, ValueError):
        return False
