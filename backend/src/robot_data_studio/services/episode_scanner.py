from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..db import transaction
from ..episode_contract import inspect_episode
from .session_service import get_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def scan_session(session_id: str) -> dict:
    session = get_session(session_id)
    if not session:
        raise KeyError(session_id)
    root = Path(session["config"]["episode_root"]).resolve()
    indexed = skipped = invalid = 0
    for manifest_path in sorted(root.glob("episode_*/manifest.json")):
        try:
            episode = inspect_episode(manifest_path, engine_id=session["engine_id"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            invalid += 1
            continue
        with transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM episodes WHERE episode_uuid = ?", (episode.episode_uuid,)
            ).fetchone()
            if existing:
                skipped += 1
                continue
            connection.execute(
                """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
                   auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    episode.episode_uuid,
                    str(manifest_path.parent.resolve()),
                    episode.task,
                    None if episode.operator_success is None else int(episode.operator_success),
                    None if episode.auto_success is None else int(episode.auto_success),
                    episode.failure_reason,
                    episode.num_frames,
                    json.dumps(episode.manifest),
                    episode.created_at,
                    _now(),
                ),
            )
            indexed += 1
    return {"indexed": indexed, "skipped": skipped, "invalid": invalid}


def list_episodes(session_id: str | None = None, qa_status: str | None = None) -> list[dict]:
    clauses: list[str] = []
    params: list[str] = []
    if session_id:
        clauses.append("e.session_id = ?")
        params.append(session_id)
    if qa_status:
        clauses.append("e.qa_status = ?")
        params.append(qa_status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with transaction() as connection:
        rows = connection.execute(
            f"""SELECT e.id, e.session_id, e.episode_uuid, e.path, e.task, e.operator_success,
                e.auto_success, e.qa_status, e.failure_reason, e.num_frames, e.created_at,
                s.dataset_id FROM episodes e JOIN sessions s ON s.id = e.session_id
                {where} ORDER BY COALESCE(e.created_at, e.indexed_at) DESC""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def episode_detail(episode_id: int) -> dict | None:
    with transaction() as connection:
        row = connection.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["manifest"] = json.loads(result.pop("manifest_json"))
    trajectory = Path(result["path"]) / "trajectory.npz"
    result["trajectory"] = {}
    if trajectory.exists():
        with np.load(trajectory, allow_pickle=False) as arrays:
            for name in ("timestamp", "policy_state", "policy_action", "reward"):
                if name in arrays:
                    values = arrays[name]
                    stride = max(1, len(values) // 200)
                    result["trajectory"][name] = values[::stride].tolist()
    return result


def update_qa(episode_id: int, qa_status: str, failure_reason: str | None) -> dict | None:
    with transaction() as connection:
        connection.execute(
            "UPDATE episodes SET qa_status = ?, failure_reason = ? WHERE id = ?",
            (qa_status, failure_reason, episode_id),
        )
        row = connection.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    return dict(row) if row else None
