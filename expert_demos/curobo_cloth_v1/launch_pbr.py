"""Capture Isaac logs and require artifact verification; Kit exit code alone is insufficient."""
import argparse,subprocess,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--gpu',default='3');a=p.parse_args()
run=Path(a.run)
with (run/'pbr_render.log').open('x') as log:
    r=subprocess.run(['/data/zhanghejun/isaacsim_6.0.1/python.sh',str(ROOT/'render_pbr.py'),str(run),'--gpu',a.gpu],stdout=log,stderr=subprocess.STDOUT)
path=run/'pbr_replay/verification.json'
if not path.exists():raise RuntimeError('PBR verification missing; inspect '+str(run/'pbr_render.log'))
v=json.loads(path.read_text())
if v['preview_only'] or v['physics_steps']!=0 or not v['cloth_vertices_exact']:raise RuntimeError('PBR state verification failed')
print(json.dumps({k:v[k] for k in ['renderer','robot_body_max_position_error_m','robot_body_max_rotation_error_rad','video']}))
