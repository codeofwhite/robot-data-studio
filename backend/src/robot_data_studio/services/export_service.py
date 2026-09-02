from __future__ import annotations

import os
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..adapters.clothtwin import ClothTwinAdapter
from ..config import CONTRACTS_SRC, settings
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
    episodes = _resolve_selected_episodes(payload.dataset_id, payload.episode_ids)
    export_id = uuid.uuid4().hex[:12]
    output_root = Path(dataset["root_path"]) / "exports"
    suffix = ".hdf5" if payload.format == "robomimic" else ""
    output_path = output_root / f"{payload.output_name}{suffix}"
    _validate_output_available(payload.dataset_id, output_path)
    output_root.mkdir(parents=True, exist_ok=True)
    input_root = _stage_selected_episodes(episodes, output_root / "inputs" / export_id)
    command = ClothTwinAdapter().build_export_command(
        payload.format, input_root, output_path, repo_id=payload.repo_id,
        images=payload.images, profile=payload.profile,
    )
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """INSERT INTO exports(id, dataset_id, format, status, output_path, error,
               worker_pid, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', ?, NULL, NULL, ?, ?)""",
            (export_id, payload.dataset_id, payload.format, str(output_path), timestamp, timestamp),
        )
        connection.execute(
            """INSERT INTO export_specs(export_id, output_name, repo_id, images, profile)
               VALUES (?, ?, ?, ?, ?)""",
            (export_id, payload.output_name, payload.repo_id, int(payload.images), payload.profile),
        )
        connection.executemany(
            "INSERT INTO export_episodes(export_id, episode_id, position) VALUES (?, ?, ?)",
            [(export_id, episode["id"], position) for position, episode in enumerate(episodes)],
        )
    log_path = output_root / f"{export_id}.log"
    try:
        with log_path.open("ab", buffering=0) as log_file:
            process = subprocess.Popen(
                command,
                cwd=settings.clothtwin_root,
                env=_export_environment(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as error:
        _update(export_id, "failed", str(error))
    else:
        _update(export_id, "running", pid=process.pid)
        threading.Thread(target=_wait_for_export, args=(export_id, process), daemon=True).start()
    return get_export(export_id) | {"command": command, "log_path": str(log_path)}


def _resolve_selected_episodes(dataset_id: int, episode_ids: list[int]) -> list[dict]:
    """Resolve and validate an ordered, explicitly selected accepted-only set."""
    if not episode_ids:
        raise ValueError("select at least one QA-accepted episode")
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("episode selection contains duplicates")
    placeholders = ",".join("?" for _ in episode_ids)
    with transaction() as connection:
        rows = connection.execute(
            f"""SELECT e.id, e.episode_uuid, e.path, e.qa_status, s.status AS session_status,
               s.dataset_id, d.root_path AS dataset_root FROM episodes e
               JOIN sessions s ON s.id = e.session_id
               JOIN datasets d ON d.id = s.dataset_id
               WHERE e.id IN ({placeholders})""",
            episode_ids,
        ).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    selected: list[dict] = []
    for episode_id in episode_ids:
        episode = by_id.get(episode_id)
        if episode is None or episode["dataset_id"] != dataset_id:
            raise ValueError(f"episode {episode_id} does not belong to dataset {dataset_id}")
        if episode["qa_status"] != "accepted":
            raise ValueError(f"episode {episode_id} is not QA-accepted")
        if episode["session_status"] == "trashed":
            raise ValueError(f"episode {episode_id} belongs to a trashed session")
        source = Path(episode["path"]).resolve()
        raw_root = (Path(episode["dataset_root"]).resolve() / "raw").resolve()
        if not source.is_relative_to(raw_root) or not source.is_dir():
            raise ValueError(f"episode {episode_id} source directory is unavailable")
        episode["source"] = source
        selected.append(episode)
    return selected


def _stage_selected_episodes(episodes: list[dict], staging_root: Path) -> Path:
    """Build an immutable symlink view containing exactly the selected episodes."""
    staging_root.mkdir(parents=True, exist_ok=False)
    for episode in episodes:
        source = episode["source"]
        target = staging_root / episode["episode_uuid"]
        target.mkdir()
        for child in source.iterdir():
            (target / child.name).symlink_to(child, target_is_directory=child.is_dir())
    return staging_root


def _validate_output_available(dataset_id: int, output_path: Path) -> None:
    if output_path.exists():
        raise ValueError(f"export output already exists: {output_path.name}")
    with transaction() as connection:
        active = connection.execute(
            """SELECT id FROM exports WHERE dataset_id = ? AND output_path = ?
               AND status IN ('queued', 'running', 'completed') LIMIT 1""",
            (dataset_id, str(output_path)),
        ).fetchone()
    if active:
        raise ValueError(f"export output is already reserved by job {active['id']}")


def _export_environment() -> dict[str, str]:
    env = dict(os.environ)
    python_paths = [str(CONTRACTS_SRC)]
    if env.get("PYTHONPATH"):
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    return env


def get_export(export_id: str) -> dict | None:
    with transaction() as connection:
        row = connection.execute(
            """SELECT x.*, s.output_name, s.repo_id, s.images, s.profile,
               (SELECT COUNT(*) FROM export_episodes ee WHERE ee.export_id = x.id) AS episode_count
               FROM exports x LEFT JOIN export_specs s ON s.export_id = x.id
               WHERE x.id = ?""",
            (export_id,),
        ).fetchone()
        if not row:
            return None
        episode_rows = connection.execute(
            "SELECT episode_id FROM export_episodes WHERE export_id = ? ORDER BY position",
            (export_id,),
        ).fetchall()
    result = dict(row)
    result["episode_ids"] = [episode["episode_id"] for episode in episode_rows]
    return result


def list_exports() -> list[dict]:
    with transaction() as connection:
        rows = connection.execute(
            """SELECT x.*, s.output_name, s.repo_id, s.images, s.profile,
               (SELECT COUNT(*) FROM export_episodes ee WHERE ee.export_id = x.id) AS episode_count
               FROM exports x LEFT JOIN export_specs s ON s.export_id = x.id
               ORDER BY x.created_at DESC"""
        ).fetchall()
        episode_rows = connection.execute(
            "SELECT export_id, episode_id FROM export_episodes ORDER BY export_id, position"
        ).fetchall()
    episode_ids: dict[str, list[int]] = {}
    for episode in episode_rows:
        episode_ids.setdefault(episode["export_id"], []).append(episode["episode_id"])
    return [dict(row) | {"episode_ids": episode_ids.get(row["id"], [])} for row in rows]
