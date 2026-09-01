from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..adapters import canonical_engine_id, get_engine
from ..config import settings
from ..db import transaction
from ..models import SessionCreate


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_dict(row):
    if row is None:
        return None
    result = dict(row)
    if "config_json" in result:
        result["config"] = json.loads(result.pop("config_json"))
    if "adapter_id" in result:
        result["engine_id"] = canonical_engine_id(result["adapter_id"])
    return result


def create_session(payload: SessionCreate) -> dict:
    adapter = get_engine(payload.engine_id)
    adapter.validate_config(payload.model_dump())
    timestamp = now()
    session_id = uuid.uuid4().hex[:12]
    dataset_root = (settings.data_root / "datasets" / payload.dataset_name).resolve()
    allowed_root = (settings.data_root / "datasets").resolve()
    if not dataset_root.is_relative_to(allowed_root):
        raise ValueError("dataset path escapes data root")
    episode_root = dataset_root / "raw" / session_id
    episode_root.mkdir(parents=True, exist_ok=True)
    config = payload.model_dump()
    config["episode_root"] = str(episode_root)
    with transaction() as connection:
        project = connection.execute("SELECT id FROM projects WHERE name = ?", ("local",)).fetchone()
        if project is None:
            cursor = connection.execute(
                "INSERT INTO projects(name, root_path, created_at) VALUES (?, ?, ?)",
                ("local", str(settings.data_root), timestamp),
            )
            project_id = cursor.lastrowid
        else:
            project_id = project["id"]
        dataset = connection.execute("SELECT id FROM datasets WHERE root_path = ?", (str(dataset_root),)).fetchone()
        if dataset is None:
            cursor = connection.execute(
                "INSERT INTO datasets(project_id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
                (project_id, payload.dataset_name, str(dataset_root), timestamp),
            )
            dataset_id = cursor.lastrowid
        else:
            dataset_id = dataset["id"]
        connection.execute(
            """INSERT INTO sessions(id, dataset_id, adapter_id, scene_id, control_mode, status,
               target_episodes, collector_url, worker_pid, config_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, NULL, ?, ?, ?)""",
            (session_id, dataset_id, adapter.adapter_id, payload.scene_id, payload.control_mode, payload.target_episodes,
             f"http://127.0.0.1:{payload.port}", json.dumps(config), timestamp, timestamp),
        )
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row_dict(row)


def get_session(session_id: str) -> dict | None:
    with transaction() as connection:
        row = connection.execute(
            """SELECT s.*, d.name AS dataset_name, d.root_path AS dataset_root,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id) AS episode_count,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id AND e.qa_status = 'accepted') AS accepted_count,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id AND e.qa_status = 'pending') AS pending_count
               FROM sessions s JOIN datasets d ON d.id = s.dataset_id WHERE s.id = ?""",
            (session_id,),
        ).fetchone()
    return row_dict(row)


def list_sessions() -> list[dict]:
    with transaction() as connection:
        rows = connection.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
    return [row_dict(row) for row in rows]


def update_worker(session_id: str, *, status: str, pid: int | None) -> None:
    with transaction() as connection:
        connection.execute(
            "UPDATE sessions SET status = ?, worker_pid = ?, updated_at = ? WHERE id = ?",
            (status, pid, now(), session_id),
        )
