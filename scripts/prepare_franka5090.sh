#!/usr/bin/env bash
set -euo pipefail
DEPLOY_STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)" python3 - "$@" <<'PY'
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import tarfile
import urllib.request
import urllib.parse

studio = Path(os.environ['DEPLOY_STUDIO_ROOT']).resolve()
manifest = json.loads((studio / 'deploy/franka5090/manifest.json').read_text())
parser = argparse.ArgumentParser(description='Prepare pinned FR3/GELLO code and assets; never install packages or launch a robot.')
parser.add_argument('--workspace', type=Path, default=studio.parent)
parser.add_argument('--archive', type=Path, help='Use an already downloaded release archive')
parser.add_argument('--verify-archive', type=Path, help='Validate archive only; do not write files')
parser.add_argument('--github-token-file', type=Path, help='Private GitHub API token file; never copied into deployment')
parser.add_argument('--assets-only', action='store_true', help='Only materialize verified assets; do not clone repositories')
args = parser.parse_args()
workspace = args.workspace.expanduser().resolve()

def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()

def validate(archive):
    spec = manifest['assets']
    if archive.stat().st_size != spec['size_bytes'] or digest(archive) != spec['sha256']:
        raise ValueError('Asset archive size/SHA256 mismatch; no extraction performed')
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        if len(members) != len(spec['files']) or {m.name for m in members} != set(spec['files']):
            raise ValueError('Archive member set differs from pinned manifest')
        for member in members:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe archive member: ' + member.name)
            if path.parts[0] not in ('robot-data-studio', 'gello-remote'):
                raise ValueError('Unexpected asset destination: ' + member.name)
            expected = spec['files'][member.name]
            content = tar.extractfile(member).read()
            if len(content) != expected['size_bytes'] or hashlib.sha256(content).hexdigest() != expected['sha256']:
                raise ValueError('Asset content mismatch: ' + member.name)
    return spec

if args.verify_archive:
    spec = validate(args.verify_archive.expanduser().resolve())
    print('Verified archive:', len(spec['files']), 'files; no writes')
    raise SystemExit(0)

if args.archive:
    archive = args.archive.expanduser().resolve()
else:
    cache = studio / 'data/deploy/franka5090'
    archive = cache / manifest['assets']['filename']
    if not archive.exists():
        token_path = (args.github_token_file or Path.home() / '.config/cloth-teleop/github-release.token').expanduser()
        token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not token and token_path.is_file():
            info = token_path.stat()
            if info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise PermissionError('Token file must belong to this user and have mode 600: ' + str(token_path))
            token = token_path.read_text().strip()
        if not token and not shutil.which('gh'):
            raise SystemExit('Use authenticated gh, a private --github-token-file, or --archive FILE. No packages were installed.')
        cache.mkdir(parents=True, exist_ok=True)
        if token:
            class NoCrossHostAuth(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
                    if redirected and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
                        redirected.remove_header('Authorization')
                    return redirected
            opener = urllib.request.build_opener(NoCrossHostAuth())
            headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                       'User-Agent': 'cloth-teleop-deploy', 'X-GitHub-Api-Version': '2022-11-28'}
            url = 'https://api.github.com/repos/' + manifest['assets']['repository'] + '/releases/tags/' + manifest['assets']['release_tag']
            with opener.open(urllib.request.Request(url, headers=headers), timeout=30) as response:
                release = json.load(response)
            matches = [item for item in release['assets'] if item['name'] == manifest['assets']['filename']]
            if len(matches) != 1:
                raise ValueError('Pinned release asset was not found uniquely')
            asset_url = matches[0]['url']
            if urllib.parse.urlsplit(asset_url).hostname != 'api.github.com' or not asset_url.startswith('https://'):
                raise ValueError('Unexpected release API asset URL')
            with opener.open(urllib.request.Request(asset_url, headers={**headers, 'Accept': 'application/octet-stream'}), timeout=60) as response:
                with archive.open('xb') as stream:
                    shutil.copyfileobj(response, stream)
        else:
            run(['gh', 'release', 'download', manifest['assets']['release_tag'], '--repo', manifest['assets']['repository'],
                 '--pattern', manifest['assets']['filename'], '--output', str(archive)])
spec = validate(archive)

# Preflight every destination before writing any asset. Existing different files are retained.
for name, expected in spec['files'].items():
    target = (workspace / name).resolve()
    if not target.is_relative_to(workspace):
        raise ValueError('Asset path escapes workspace: ' + name)
    if target.exists() and (not target.is_file() or digest(target) != expected['sha256']):
        raise FileExistsError('Different existing asset retained: ' + str(target))

if not args.assets_only:
    if studio != workspace / 'robot-data-studio':
        raise ValueError('Clone Studio as WORKSPACE/robot-data-studio before preparing sibling repositories')
    run(['git', '-C', str(studio), 'merge-base', '--is-ancestor', manifest['studio']['feature_commit'], 'HEAD'])
    for name, entry in [('gello-remote', manifest['gello']), ('IsaacLab', manifest['isaaclab'])]:
        target = workspace / name
        env = {**os.environ, 'GIT_LFS_SKIP_SMUDGE': '1'}
        if target.exists():
            if not (target / '.git').exists():
                raise FileExistsError('Existing non-Git directory retained: ' + str(target))
            current = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
            if current != entry['commit']:
                raise ValueError(str(target) + ' is at another commit; update explicitly or choose a new workspace')
        else:
            run(['git', 'clone', '--depth', '1', '--no-checkout', entry['repository'], str(target)], env=env)
            run(['git', '-C', str(target), 'fetch', '--depth', '1', 'origin', entry['commit']], env=env)
            run(['git', '-C', str(target), 'checkout', '--detach', entry['commit']], env=env)

with tarfile.open(archive, 'r:gz') as tar:
    for member in tar.getmembers():
        target = (workspace / member.name).resolve()
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                shutil.copyfileobj(tar.extractfile(member), stream)
            target.chmod(0o644)
print('Verified/materialized asset files:', len(spec['files']))
if args.assets_only:
    raise SystemExit(0)

lab = workspace / 'IsaacLab'
patch = workspace / manifest['isaaclab']['patch']
reverse = subprocess.run(['git', '-C', str(lab), 'apply', '--reverse', '--check', str(patch)], capture_output=True)
if reverse.returncode:
    run(['git', '-C', str(lab), 'apply', '--check', str(patch)])
    run(['git', '-C', str(lab), 'apply', str(patch)])

local = studio / 'data/deploy/franka5090'
local.mkdir(parents=True, exist_ok=True)
sources = {'schema_version': 1, 'sources': {name: {'root': str(studio / 'assets/sources' / name)}
    for name in ('visual-workstation-v1', 'robot-cloth-scenes-v1', 'cc0-surfaces-v1')}}
outputs = {local / 'asset_sources.local.json': json.dumps(sources, indent=2) + '\n'}
environment = {
    'ROBOT_DATA_STUDIO_DB': str(studio / 'data/studio.db'), 'ROBOT_DATA_STUDIO_DATA_ROOT': str(studio / 'data'),
    'ROBOT_DATA_STUDIO_ASSET_ROOT': str(studio / 'assets/registry'),
    'ROBOT_DATA_STUDIO_ASSET_SOURCES': str(local / 'asset_sources.local.json'),
    'ROBOT_DATA_STUDIO_CAMERA_PROFILE_ROOT': str(studio / 'config/camera_profiles'),
    'ROBOT_DATA_STUDIO_RENDERER_PROFILE_ROOT': str(studio / 'config/renderer_profiles'),
    'ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT': str(workspace / 'gello-remote'),
    'ROBOT_DATA_STUDIO_ISAACLAB_LAUNCHER': str(lab / 'isaaclab.sh'),
    'ROBOT_DATA_STUDIO_ISAACLAB_CONDA_PREFIX': str(workspace / '.venvs/isaaclab'),
    'ROBOT_DATA_STUDIO_ISAAC_ROBOT_MODEL': 'fr3', 'ROBOT_DATA_STUDIO_ISAAC_LOCAL_DISPLAY': '1',
    'ROBOT_DATA_STUDIO_ISAAC_FR3_USD': str(studio / 'assets/sources/fr3-v1/FrankaFR3/fr3.usd'),
    'GELLO_WEB_CONSOLE_ROOT': str(workspace / 'gello-remote/deploy/console'),
    'NEXT_PUBLIC_STUDIO_API': 'http://127.0.0.1:8010/api',
}
outputs[local / 'env.sh'] = '# Generated paths only; no credentials. Source before launching Studio.\n' + ''.join(
    'export ' + key + '=' + shlex.quote(value) + '\n' for key, value in environment.items())
for path, content in outputs.items():
    if path.exists() and path.read_text() != content:
        raise FileExistsError('Different generated configuration retained: ' + str(path))
for path, content in outputs.items():
    if not path.exists():
        path.write_text(content)

print('Prepared code and assets. Environment:', local / 'env.sh')
print('Dependencies, matching Isaac Sim runtime, browser, USB permissions and native GUI run remain separate steps.')
PY
