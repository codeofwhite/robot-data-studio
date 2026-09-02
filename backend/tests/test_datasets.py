from robot_data_studio.db import transaction
from robot_data_studio.models import SessionCreate
from robot_data_studio.routes.datasets import index
from robot_data_studio.services.session_service import create_session, trash_session


def test_datasets_endpoint_lists_each_dataset_once_with_exportable_counts(
    isolated_settings,
) -> None:
    first = create_session(
        SessionCreate(
            dataset_name="pilot",
            scene_id="rigid_pick_place",
            control_mode="keyboard",
        )
    )
    second = create_session(
        SessionCreate(
            dataset_name="pilot",
            scene_id="rigid_pick_place",
            control_mode="keyboard",
        )
    )
    create_session(
        SessionCreate(
            dataset_name="other",
            scene_id="rigid_pick_place",
            control_mode="keyboard",
        )
    )
    with transaction() as connection:
        for session, qa_status, suffix in (
            (first, "accepted", "accepted"),
            (first, "pending", "pending"),
            (second, "accepted", "trashed"),
        ):
            root = isolated_settings.data_root / "datasets" / "pilot" / "raw" / session["id"]
            episode_root = root / suffix
            episode_root.mkdir(parents=True, exist_ok=True)
            connection.execute(
                """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
                   auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
                   VALUES (?, ?, ?, 'task', 1, 1, ?, NULL, 1, '{}', NULL, 'now')""",
                (session["id"], f"episode-{suffix}", str(episode_root), qa_status),
            )
    trash_session(second["id"])

    datasets = index()
    assert [dataset["name"] for dataset in datasets].count("pilot") == 1
    pilot = next(dataset for dataset in datasets if dataset["name"] == "pilot")
    assert pilot["session_count"] == 1
    assert pilot["episode_count"] == 2
    assert pilot["accepted_count"] == 1
