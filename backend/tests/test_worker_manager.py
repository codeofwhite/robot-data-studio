from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import robot_data_studio.services.worker_manager as worker_manager_module
from robot_data_studio.adapters.base import WorkerLaunch, WorkerReadiness
from robot_data_studio.db import transaction
from robot_data_studio.models import SessionCreate
from robot_data_studio.services.session_service import create_session, get_session
from robot_data_studio.services.worker_manager import WorkerManager
from robot_data_studio.services.worker_runtime import (
    ResourceConflict,
    create_run,
    get_run,
    mark_run,
    process_identity,
    run_resources,
    set_supervisor_identity,
)


FAKE_WORKER = Path(__file__).parent / "fixtures" / "fake_worker.py"
SUPERVISOR = Path(__file__).parents[1] / "src" / "robot_data_studio" / "worker_supervisor.py"


class FakeAdapter:
    adapter_id = "roboverse"

    def __init__(self, *args: str):
        self.args = list(args)

    def build_worker_launch(self, config, output_dir: Path) -> WorkerLaunch:
        return WorkerLaunch(
            command=[sys.executable, str(FAKE_WORKER), *self.args],
            cwd=output_dir,
            readiness=WorkerReadiness(kind="marker", timeout_s=2.0),
            resources=(
                "simulator:global",
                f"gpu:{config['gpu']}",
                f"output:{output_dir.resolve()}",
            ),
        )


class MissingCommandAdapter(FakeAdapter):
    def build_worker_launch(self, config, output_dir: Path) -> WorkerLaunch:
        launch = super().build_worker_launch(config, output_dir)
        return WorkerLaunch(
            command=[str(output_dir / "does-not-exist")],
            cwd=launch.cwd,
            readiness=launch.readiness,
            resources=launch.resources,
        )


def new_session(name: str) -> dict:
    return create_session(
        SessionCreate(
            engine_id="roboverse",
            dataset_name=name,
            scene_id="maniskill_pick_cube_native",
            control_mode="scripted",
            target_episodes=1,
            control_fps=20,
            camera_profile_id="roboverse_sapien_base_v1",
            scene_params={},
        )
    )


def wait_status(
    manager: WorkerManager, session_id: str, expected: str, timeout: float = 4.0
) -> dict:
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = manager.status(session_id)
        if latest["status"] == expected:
            return latest
        time.sleep(0.03)
    raise AssertionError(f"worker never reached {expected}: {latest}")


def force_cleanup(status: dict | None) -> None:
    if not status or not status.get("supervisor_pid"):
        return
    try:
        os.killpg(int(status["supervisor_pid"]), signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_manager_reconciles_same_run_after_restart(isolated_settings, monkeypatch) -> None:
    session = new_session("restart_reconcile")
    monkeypatch.setattr(worker_manager_module, "get_engine", lambda _engine: FakeAdapter())
    manager = WorkerManager(monitor_interval_s=0.05)
    status = None
    try:
        started = manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        assert status["run_id"] == started["run_id"]
        restarted_manager = WorkerManager(monitor_interval_s=0.05)
        recovered = restarted_manager.status(session["id"])
        assert recovered["status"] == "running"
        assert recovered["run_id"] == started["run_id"]
        assert recovered["heartbeat_at"] is not None
        stopped = restarted_manager.stop(session["id"])
        assert stopped["status"] == "stopped"
        status = stopped
    finally:
        force_cleanup(status)


def test_manager_recovers_supervisor_after_launching_parent_exits(
    isolated_settings,
) -> None:
    session = new_session("parent_restart_reconcile")
    output_root = Path(session["config"]["episode_root"])
    runtime_root = output_root / ".studio" / "runs" / "parent-exit-run"
    spec_path = runtime_root / "launch.json"
    state_path = runtime_root / "state.json"
    ready_path = runtime_root / "ready.json"
    log_path = output_root / "collector.log"
    create_run(
        run_id="parent-exit-run",
        session_id=session["id"],
        engine_id="roboverse",
        command=[sys.executable, str(FAKE_WORKER)],
        cwd=output_root,
        log_path=log_path,
        state_path=state_path,
        readiness={"kind": "marker", "path": str(ready_path), "timeout_s": 2.0},
        resources=("simulator:global", "gpu:0", f"output:{output_root.resolve()}"),
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        json.dumps(
            {
                "run_id": "parent-exit-run",
                "command": [sys.executable, str(FAKE_WORKER)],
                "cwd": str(output_root),
                "log_path": str(log_path),
                "state_path": str(state_path),
                "readiness": {
                    "kind": "marker",
                    "path": str(ready_path),
                    "timeout_s": 2.0,
                },
                "heartbeat_interval_s": 0.05,
                "child_stop_timeout_s": 0.1,
            }
        ),
        encoding="utf-8",
    )
    launcher = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,sys.argv[1],'--spec',sys.argv[2]],"
        "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "print(p.pid)"
    )
    env = dict(os.environ)
    env["ROBOT_DATA_STUDIO_READY_FILE"] = str(ready_path)
    parent = subprocess.run(
        [sys.executable, "-c", launcher, str(SUPERVISOR), str(spec_path)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    supervisor_pid = int(parent.stdout.strip())
    process_boot_id, start_ticks = process_identity(supervisor_pid)
    set_supervisor_identity(
        "parent-exit-run",
        pid=supervisor_pid,
        process_boot_id=process_boot_id,
        start_ticks=start_ticks,
    )
    manager = WorkerManager()
    status = None
    try:
        status = wait_status(manager, session["id"], "running")
        assert status["run_id"] == "parent-exit-run"
        assert status["heartbeat_at"] is not None
        status = manager.stop(session["id"])
        assert status["status"] == "stopped"
    finally:
        force_cleanup(status or {"supervisor_pid": supervisor_pid})


def test_manager_records_nonzero_exit_and_releases_locks(isolated_settings, monkeypatch) -> None:
    session = new_session("nonzero_exit")
    monkeypatch.setattr(
        worker_manager_module,
        "get_engine",
        lambda _engine: FakeAdapter("--exit-code", "23", "--lifetime", "0.1"),
    )
    manager = WorkerManager()
    manager.start(session["id"])
    failed = wait_status(manager, session["id"], "failed")
    assert failed["return_code"] == 23
    assert "return code 23" in failed["error"]
    assert failed["resources"] == []
    assert manager.status(session["id"])["status"] == "failed"


def test_manager_records_child_launch_failure(isolated_settings, monkeypatch) -> None:
    session = new_session("launch_failure")
    monkeypatch.setattr(
        worker_manager_module, "get_engine", lambda _engine: MissingCommandAdapter()
    )
    manager = WorkerManager()
    try:
        manager.start(session["id"])
    except OSError:
        pass
    failed = wait_status(manager, session["id"], "failed")
    assert failed["return_code"] == 127
    assert "launch failed" in failed["error"]


def test_manager_stop_handles_sigterm_and_sigkill(isolated_settings, monkeypatch) -> None:
    session = new_session("sigkill_fallback")
    monkeypatch.setattr(
        worker_manager_module,
        "get_engine",
        lambda _engine: FakeAdapter("--ignore-sigterm"),
    )
    manager = WorkerManager(stop_timeout_s=0.5, kill_timeout_s=0.5)
    status = None
    try:
        manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        stopped = manager.stop(session["id"])
        assert stopped["status"] == "stopped"
        assert stopped["return_code"] == -int(signal.SIGKILL)
        status = stopped
    finally:
        force_cleanup(status)


def test_manager_stop_records_graceful_sigterm_as_stopped(
    isolated_settings, monkeypatch
) -> None:
    session = new_session("graceful_sigterm")
    monkeypatch.setattr(worker_manager_module, "get_engine", lambda _engine: FakeAdapter())
    manager = WorkerManager(stop_timeout_s=1.0, kill_timeout_s=0.5)
    status = None
    try:
        manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        stopped = manager.stop(session["id"])
        assert stopped["status"] == "stopped"
        assert stopped["return_code"] == 0
        assert stopped["error"] is None
        assert stopped["resources"] == []
        status = stopped
    finally:
        force_cleanup(status)


def test_manager_rereads_terminal_state_before_marking_orphaned(
    isolated_settings, monkeypatch
) -> None:
    session = new_session("terminal_state_race")
    state_path = isolated_settings.data_root / "terminal-state.json"
    create_run(
        run_id="terminal-state-race-run",
        session_id=session["id"],
        engine_id="roboverse",
        command=["fake"],
        cwd=isolated_settings.data_root,
        log_path=isolated_settings.data_root / "terminal-state.log",
        state_path=state_path,
        readiness={"kind": "process", "timeout_s": 1.0},
        resources=("gpu:4",),
    )
    terminal_state = {
        "run_id": "terminal-state-race-run",
        "status": "stopped",
        "supervisor_pid": 999999,
        "child_pid": 999998,
        "ready_at": "2026-09-16T00:00:00+00:00",
        "heartbeat_at": "2026-09-16T00:00:01+00:00",
        "stopped_at": "2026-09-16T00:00:02+00:00",
        "return_code": -int(signal.SIGTERM),
        "error": None,
    }
    states = iter(
        [
            terminal_state | {"status": "stopping", "stopped_at": None},
            terminal_state,
        ]
    )
    monkeypatch.setattr(worker_manager_module, "read_state", lambda _path: next(states))
    monkeypatch.setattr(worker_manager_module, "identity_matches", lambda *_args: False)

    run = get_run("terminal-state-race-run")
    assert run is not None
    stopped = WorkerManager()._sync_run(run)
    assert stopped["status"] == "stopped"
    assert stopped["return_code"] == -int(signal.SIGTERM)
    assert run_resources("terminal-state-race-run") == []


def test_manager_refuses_pid_identity_mismatch(isolated_settings, monkeypatch) -> None:
    session = new_session("identity_mismatch")
    monkeypatch.setattr(worker_manager_module, "get_engine", lambda _engine: FakeAdapter())
    manager = WorkerManager()
    status = None
    try:
        manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        with transaction() as connection:
            connection.execute(
                "UPDATE worker_runs SET supervisor_start_ticks = supervisor_start_ticks + 1 WHERE run_id = ?",
                (status["run_id"],),
            )
        orphaned = manager.status(session["id"])
        assert orphaned["status"] == "orphaned"
        assert "identity" in orphaned["error"]
        assert orphaned["resources"] == []
    finally:
        force_cleanup(status)


def test_manager_fails_stale_heartbeat_and_releases_locks(
    isolated_settings, monkeypatch
) -> None:
    session = new_session("stale_heartbeat")
    monkeypatch.setattr(worker_manager_module, "get_engine", lambda _engine: FakeAdapter())
    manager = WorkerManager(heartbeat_stale_s=1.5)
    status = None
    try:
        manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        os.killpg(int(status["supervisor_pid"]), signal.SIGSTOP)
        time.sleep(1.6)
        failed = manager.status(session["id"])
        assert failed["status"] == "failed"
        assert "heartbeat" in failed["error"]
        assert failed["resources"] == []
        assert manager.status(session["id"])["status"] == "failed"
        status = failed
    finally:
        force_cleanup(status)


def test_resource_locks_report_all_conflicts(isolated_settings) -> None:
    first = new_session("lock_first")
    second = new_session("lock_second")
    resources = ("gpu:4", "tcp:18080", "output:/tmp/shared-output")
    create_run(
        run_id="first-run",
        session_id=first["id"],
        engine_id="roboverse",
        command=["fake"],
        cwd=Path("/tmp"),
        log_path=Path("/tmp/first.log"),
        state_path=Path("/tmp/first-state.json"),
        readiness={"kind": "process", "timeout_s": 1},
        resources=resources,
    )
    with pytest.raises(ResourceConflict) as caught:
        create_run(
            run_id="second-run",
            session_id=second["id"],
            engine_id="roboverse",
            command=["fake"],
            cwd=Path("/tmp"),
            log_path=Path("/tmp/second.log"),
            state_path=Path("/tmp/second-state.json"),
            readiness={"kind": "process", "timeout_s": 1},
            resources=resources,
        )
    assert {item["resource_key"] for item in caught.value.conflicts} == set(resources)
    mark_run("first-run", status="failed", error="test cleanup")
    assert run_resources("first-run") == []


def test_legacy_running_session_becomes_orphaned(isolated_settings) -> None:
    session = new_session("legacy_orphan")
    with transaction() as connection:
        connection.execute(
            "UPDATE sessions SET status = 'running', worker_pid = 999999 WHERE id = ?",
            (session["id"],),
        )
    result = WorkerManager().reconcile()
    assert result["legacy_orphans"] == [session["id"]]
    reconciled = get_session(session["id"])
    assert reconciled["status"] == "orphaned"
    assert reconciled["worker_pid"] is None
