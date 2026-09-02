from __future__ import annotations

from ..db import transaction


def list_datasets() -> list[dict]:
    """List datasets with counts matching the accepted-only export scope."""
    with transaction() as connection:
        rows = connection.execute(
            """SELECT d.id, d.name, d.root_path, d.created_at,
               COUNT(DISTINCT CASE WHEN s.status != 'trashed' THEN s.id END) AS session_count,
               COUNT(DISTINCT CASE WHEN s.status != 'trashed' THEN e.id END) AS episode_count,
               COUNT(DISTINCT CASE
                   WHEN s.status != 'trashed' AND e.qa_status = 'accepted' THEN e.id
               END) AS accepted_count
               FROM datasets d
               LEFT JOIN sessions s ON s.dataset_id = d.id
               LEFT JOIN episodes e ON e.session_id = s.id
               GROUP BY d.id, d.name, d.root_path, d.created_at
               ORDER BY d.created_at DESC, d.id DESC"""
        ).fetchall()
    return [dict(row) for row in rows]
