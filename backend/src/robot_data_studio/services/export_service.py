from __future__ import annotations

import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..adapters.clothtwin import ClothTwinAdapter
from ..config import settings
from ..db import transaction
from ..models import ExportCreate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update(export_id: str, status: str, error: str | None = None, pid: int | None = None) -> None:
    with transaction() as connection:
        connection.execute(
            "UPDATE exports SET status = ?, error = ?, worker_pid = ?, updated_at = ? WHERE id = ?",
            (status, error, pid, _now(), export_id),
        )


def _wait_for_export(export_id: str, process: subprocess.Popen) -> None:
    return_code = process.wait()
    _update(export_id, "completed" if return_code == 0 else "failed", None if return_code == 0 else f"export process exited {return_code}")


def create_export(payload: ExportCreate) -> dict:
    with transaction() as connection:
        dataset = connection.execute("SELECT * FROM datasets WHERE id = ?", (payload.dataset_id,)).fetchone()
    if not dataset:
        raise KeyError(payload.dataset_id)
    export_id = uuid.uuid4().hex[:12]
    output_root = Path(dataset["root_path"]) / "exports"
    output_root.mkdir(parents=True, exist_ok=True)
    input_root = _accepted_input_root(payload.dataset_id, output_root / "inputs" / export_id)
    suffix = ".hdf5" if payload.format == "robomimic" else ""
    output_path = output_root / f"{payload.output_name}{suffix}"
    command = ClothTwinAdapter().build_export_command(payload.format, input_root, output_path, repo_id=payload.repo_id, images=payload.images)
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            "INSERT INTO exports VALUES (?, ?, ?, 'queued', ?, NULL, NULL, ?, ?)",
            (export_id, payload.dataset_id, payload.format, str(output_path), timestamp, timestamp),
        )
    log_path = output_root / f"{export_id}.log"
    log_file = log_path.open("ab", buffering=0)
    try:
        process = subprocess.Popen(command, cwd=settings.clothtwin_root, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as error:
        _update(export_id, "failed", str(error))
    else:
        _update(export_id, "running", pid=process.pid)
        threading.Thread(target=_wait_for_export, args=(export_id, process), daemon=True).start()
    return get_export(export_id) | {"command": command, "log_path": str(log_path)}


def _accepted_input_root(dataset_id: int, staging_root: Path) -> Path:
    """Build a lightweight, immutable view containing only QA-accepted episodes."""
    with transaction() as connection:
        rows = connection.execute(
            """SELECT e.episode_uuid, e.path FROM episodes e
               JOIN sessions s ON s.id = e.session_id
               WHERE s.dataset_id = ? AND e.qa_status = 'accepted'""",
            (dataset_id,),
        ).fetchall()
    if not rows:
        raise ValueError("dataset has no QA-accepted episodes")
    staging_root.mkdir(parents=True, exist_ok=False)
    for row in rows:
        source = Path(row["path"]).resolve()
        target = staging_root / row["episode_uuid"]
        target.mkdir()
        for child in source.iterdir():
            (target / child.name).symlink_to(child, target_is_directory=child.is_dir())
    return staging_root


def get_export(export_id: str) -> dict | None:
    with transaction() as connection:
        row = connection.execute("SELECT * FROM exports WHERE id = ?", (export_id,)).fetchone()
    return dict(row) if row else None


def list_exports() -> list[dict]:
    with transaction() as connection:
        rows = connection.execute("SELECT * FROM exports ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]
