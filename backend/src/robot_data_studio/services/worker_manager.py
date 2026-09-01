from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from ..adapters import get_engine
from .session_service import get_session, update_worker


@dataclass
class Worker:
    process: subprocess.Popen
    log_path: Path
    engine_id: str


class WorkerManager:
    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}
        self._lock = threading.Lock()

    def command_for(self, session: dict) -> list[str]:
        adapter = get_engine(session["engine_id"])
        launch = adapter.build_worker_launch(
            session["config"], Path(session["config"]["episode_root"])
        )
        return launch.command

    def _active_worker(self, *, excluding: str | None = None) -> tuple[str, Worker] | None:
        for managed_session_id, worker in self._workers.items():
            if managed_session_id != excluding and worker.process.poll() is None:
                return managed_session_id, worker
        return None

    def start(self, session_id: str) -> dict:
        session = get_session(session_id)
        if not session:
            raise KeyError(session_id)
        with self._lock:
            existing = self._workers.get(session_id)
            if existing and existing.process.poll() is None:
                return {"status": "running", "pid": existing.process.pid, "command": self.command_for(session)}
            active = self._active_worker(excluding=session_id)
            if active is not None:
                active_session_id, active_worker = active
                raise RuntimeError(
                    f"simulator worker {active_session_id} is already running "
                    f"on engine {active_worker.engine_id}; stop it before switching engines"
                )
            adapter = get_engine(session["engine_id"])
            launch = adapter.build_worker_launch(
                session["config"], Path(session["config"]["episode_root"])
            )
            command = launch.command
            log_path = Path(session["config"]["episode_root"]) / "collector.log"
            log_file = log_path.open("ab", buffering=0)
            env = dict(os.environ)
            for name in launch.unset_env:
                env.pop(name, None)
            env.update(launch.env_updates)
            process = subprocess.Popen(
                command,
                cwd=launch.cwd,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self._workers[session_id] = Worker(process, log_path, adapter.adapter_id)
            update_worker(session_id, status="starting", pid=process.pid)
            return {"status": "starting", "pid": process.pid, "command": command, "log_path": str(log_path)}

    def status(self, session_id: str) -> dict:
        worker = self._workers.get(session_id)
        if not worker:
            return {"status": "not_managed", "pid": None}
        return_code = worker.process.poll()
        status = "running" if return_code is None else ("stopped" if return_code == 0 else "failed")
        update_worker(session_id, status=status, pid=worker.process.pid if return_code is None else None)
        return {
            "status": status,
            "pid": worker.process.pid,
            "return_code": return_code,
            "log_path": str(worker.log_path),
            "engine_id": worker.engine_id,
        }

    def stop(self, session_id: str) -> dict:
        worker = self._workers.get(session_id)
        if not worker or worker.process.poll() is not None:
            update_worker(session_id, status="stopped", pid=None)
            return {"status": "stopped", "pid": None}
        os.killpg(worker.process.pid, signal.SIGTERM)
        try:
            worker.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(worker.process.pid, signal.SIGKILL)
            worker.process.wait(timeout=3)
        update_worker(session_id, status="stopped", pid=None)
        return {"status": "stopped", "pid": worker.process.pid}


worker_manager = WorkerManager()
