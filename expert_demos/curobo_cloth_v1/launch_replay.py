import argparse,subprocess,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--gpu',default='3');a=p.parse_args();run=Path(a.run)
env=os.environ.copy();env['CLOTH_GPU']=a.gpu
with (run/'replay_render.log').open('x') as log:
    r=subprocess.run(['python3','-B',str(ROOT/'launch.py'),'render_replay.py',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
if r.returncode:raise RuntimeError('Replay failed: '+str(run/'replay_render.log'))
v=json.loads((run/'replay/verification.json').read_text());print(json.dumps({'native_episode_valid':v['native_episode_valid'],'videos':v['videos'],'episode_path':v['episode_path']}))
