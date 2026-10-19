#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:---local-display}"
case "$mode" in
  --local-display|--remote-preview) ;;
  *) echo "Usage: $0 [--local-display|--remote-preview]" >&2; exit 2 ;;
esac
source "$STUDIO_ROOT/data/deploy/franka5090/env.sh"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export ROBOT_DATA_STUDIO_ENABLED_ENGINES="${ROBOT_DATA_STUDIO_ENABLED_ENGINES-isaac_sim}"
export ROBOT_DATA_STUDIO_PUBLIC_IP="${ROBOT_DATA_STUDIO_PUBLIC_IP:-127.0.0.1}"
if [[ "$mode" == --remote-preview ]]; then
  export ROBOT_DATA_STUDIO_ISAAC_LOCAL_DISPLAY=0
else
  if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    echo "Log into your own graphical desktop before --local-display." >&2
    exit 1
  fi
  export ROBOT_DATA_STUDIO_ISAAC_LOCAL_DISPLAY=1
fi
export FRANKA5090_STUDIO_ROOT="$STUDIO_ROOT"
exec "$STUDIO_ROOT/backend/.venv/bin/python" - <<'PYTHON'
import datetime, os, shutil, signal, socket, subprocess, time
from pathlib import Path
root = Path(os.environ['FRANKA5090_STUDIO_ROOT'])
if not shutil.which('node') or not shutil.which('npm'):
    raise SystemExit('Node and npm must be installed before launch.')
if not (root / 'node_modules/vinext').is_dir():
    raise SystemExit('Frontend dependencies missing; run the approved npm ci step first.')
for port in (3000, 8010):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as error:
            raise SystemExit(f'Port {port} is occupied; existing service retained: {error}')
run = root / 'data/deploy/franka5090' / ('launch_' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
run.mkdir()
commands = {
    'api': [str(root / 'backend/.venv/bin/python'), '-m', 'uvicorn', 'robot_data_studio.main:app', '--app-dir', str(root / 'backend/src'), '--host', '127.0.0.1', '--port', '8010'],
    'ui': ['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '3000'],
}
def stop_requested(signum, frame):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, stop_requested)
children = []
streams = []
try:
    for name, command in commands.items():
        stream = (run / (name + '.log')).open('x')
        streams.append(stream)
        process = subprocess.Popen(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        children.append((name, process))
    print('Studio: http://127.0.0.1:3000', flush=True)
    print('API: http://127.0.0.1:8010/docs', flush=True)
    print('Logs:', run, flush=True)
    print('Stop the simulator in Studio before Ctrl+C closes UI/API.', flush=True)
    while True:
        for name, process in children:
            status = process.poll()
            if status is not None:
                raise SystemExit(f'{name} exited with status {status}; inspect {run / (name + ".log")}')
        time.sleep(0.25)
except KeyboardInterrupt:
    pass
finally:
    # Each child owns a new process group; never signal unrelated desktop jobs.
    for _, process in children:
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _, process in children:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    for stream in streams:
        stream.close()
PYTHON
