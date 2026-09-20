"""Directory-safe batch driver using the existing three local environments."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import fcntl

HERE=Path(__file__).resolve().parent;CORE=HERE.parent;PROJECT=CORE.parents[1]
DATA=PROJECT/'data/expert_demos/curobo-cloth-v1';BATCH=DATA/'fixtures_v4'
PY='/data/zhanghejun/miniconda3/envs/genesis/bin/python'
PLANNER='/data/zhanghejun/SIMPLE/.venv/bin/python'
ISAAC='/data/zhanghejun/isaacsim_6.0.1/python.sh'
BACKEND=str(PROJECT/'backend/.venv/bin/python')
sys.path.insert(0,str(CORE))
from fixtures_v4 import TASKS,catalog


def environment(device=0):
    mask=os.environ.get('CUDA_VISIBLE_DEVICES')
    if mask not in ('0,1','1','2,3','4','5','6'):raise RuntimeError('Use CUDA_VISIBLE_DEVICES=0,1, 1, 2,3, 4, 5 or 6')
    if device>=len(mask.split(',')):raise ValueError('Logical GPU is outside the explicit mask')
    env=dict(os.environ,CUDA_VISIBLE_DEVICES=mask,CUDA_LAUNCH_BLOCKING='0',PYTHONDONTWRITEBYTECODE='1',
             PYOPENGL_PLATFORM='egl',EGL_DEVICE_ID=mask.split(',')[device],OMP_NUM_THREADS='4')
    for key,name in [('GS_CACHE_FILE_PATH','genesis'),('XDG_CACHE_HOME',''),('TMPDIR','tmp'),
                     ('NUMBA_CACHE_DIR','numba'),('MPLCONFIGDIR','matplotlib'),('TORCH_EXTENSIONS_DIR','torch_extensions')]:
        dest=DATA/'cache'/name;dest.mkdir(parents=True,exist_ok=True);env[key]=str(dest)
    return env


def call(cmd,log,device=0,allowed_returncodes=(0,)):
    log=Path(log);log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('x') as f:
        result=subprocess.run(cmd,cwd=PROJECT,env=environment(device),stdout=f,stderr=subprocess.STDOUT)
    if result.returncode not in allowed_returncodes:raise RuntimeError('Command failed; see '+str(log))
    return result.returncode


def preflight(task,variant,device=0):
    from fixtures_v4.build_scenes import build
    from fixtures_v4.actions import grasp_position
    import numpy as np
    from scipy.spatial.transform import Rotation
    build(task,variant);out=BATCH/'diagnostics'/task/variant;out.mkdir(parents=True,exist_ok=True)
    plan=out/'initialization_plan.json'
    if plan.exists():return plan
    prepared=out/'prepared';scene='fxv4_'+task+'_'+variant
    if not prepared.exists():
        call([PY,'-B',str(CORE/'runner.py'),'--scene',scene,'--task',task,'--visual-demo-profile','--physics-device',str(device),'--prepare-only','--output',str(prepared)],out/'prepare.log',device)
    cfg=json.loads((prepared/'config.json').read_text());topology=json.loads(Path(cfg['scene_binding']['topology_path']).read_text())
    primary=cfg['task_spec']['primary_corner'];points=np.asarray(topology['initial_vertices']);f=cfg['task_spec']['fixture']
    top=f['center_height_m']+f['radius_m'] if f['kind']=='rod' else f['base_height_m']+f['size_m'][2]
    quat=(Rotation.from_euler('z',90,degrees=True)*Rotation.from_euler('x',180,degrees=True)).as_quat()[[3,0,1,2]].tolist()
    number=1
    while (out/('search_%03d'%number)).exists():number+=1
    search=out/('search_%03d'%number);search.mkdir();(search/'config.json').write_text(json.dumps(cfg,indent=2))
    from runner import PlannerProcess
    worker=PlannerProcess(search,cfg);selected=None
    try:
        candidates=[primary,188,147,168,20,335,0,315]
        if task=='retrieve_from_rod':
            # A settled two-sided drape can leave every corner below the rod.
            # Try the actually observed upper boundary rather than requiring
            # an unreachable corner or changing the collision geometry.
            edges={}
            for face in topology['faces']:
                for a,b in zip(face,face[1:]+face[:1]):
                    edge=tuple(sorted((a,b)));edges[edge]=edges.get(edge,0)+1
            boundary={i for edge,count in edges.items() if count==1 for i in edge}
            candidates+=sorted(boundary,key=lambda i:points[i,2],reverse=True)
        for index in dict.fromkeys(candidates):
            point=points[index];contact=grasp_position(point,cfg)
            probe=worker.call(dict(q=cfg['home'][:7],tcp_world=contact,quaternion_wxyz=quat,purpose='initial_grasp_probe'))
            print('GRASP_PROBE',task,index,probe.get('success'),probe.get('status'),flush=True)
            if not probe.get('success'):continue
            hover=[*point[:2],max(top+.13,point[2]+.12)]
            result=worker.call(dict(q=cfg['home'][:7],tcp_world=hover,quaternion_wxyz=quat,purpose='initial_hover'))
            if result.get('success'):selected=index;break
    finally:worker.close()
    if selected is None:raise RuntimeError('No reachable grasp/hover in fixture scene; see '+str(search))
    result['grasp_seed']=dict(vertex_index=selected,quaternion_wxyz=quat,approach_offset_m=[0,0,.12])
    plan.write_text(json.dumps(result,indent=2));return plan


def latest_run(task,variant):
    root=BATCH/'tasks'/task/variant/'runs'
    paths=sorted(root.glob('*')) if root.exists() else []
    return paths[-1] if paths else None


def run_one(task,variant,device=0):
    plan=preflight(task,variant,device)
    seed=catalog()['seed'];stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dt%H%M%S')
    ident='fxv4-'+task.replace('_','-')+'-'+variant+'-'+stamp
    run=BATCH/'tasks'/task/variant/'runs'/ident;run.parent.mkdir(parents=True,exist_ok=True)
    log=BATCH/'reports/logs'/(ident+'.log')
    print('RUN_START',ident,'physics_device',device,flush=True)
    returncode=call([PY,'-B','-u',str(CORE/'runner.py'),'--scene','fxv4_'+task+'_'+variant,'--task',task,
          '--scene-hover-plan',str(plan),'--visual-demo-profile','--physics-device',str(device),
          '--seed',str(seed),'--output',str(run)],log,device,allowed_returncodes=(0,2))
    if returncode==2 and not (run/'run_summary.json').exists():
        raise RuntimeError('Runner returned 2 without a saved summary; see '+str(log))
    mask=os.environ['CUDA_VISIBLE_DEVICES']
    provenance=BATCH/'reports'/('environment.json' if mask=='2,3' else 'environment_gpu'+mask+'.json')
    if provenance.exists():
        value=json.loads(provenance.read_text());value.update(run=ident,physics_cuda_device=device)
        (run/'environment_provenance.json').write_text(json.dumps(value,indent=2))
    (run/'launch.json').write_text(json.dumps(dict(log=str(log),CUDA_VISIBLE_DEVICES=mask,physics_device=device,initialization_plan=str(plan),runner_returncode=returncode),indent=2))
    call([PY,'-B',str(CORE/'evaluate.py'),str(run)],BATCH/'reports/logs'/(ident+'-evaluation.log'),device)
    ev=json.loads((run/'evaluation.json').read_text());print('RUN_END',ident,'success',ev['success'],'failed_gates',ev['failed_gates'],flush=True)
    return run


def render_one(run,device=0):
    for name,camera,fps in [('pbr_replay','hero','5'),('pbr_overhead','overhead','2')]:
        if (run/name/'verification.json').exists():continue
        log=BATCH/'reports/logs'/(run.name+'-'+name+'.log');attempt=2
        while log.exists():
            log=BATCH/'reports/logs'/(run.name+'-'+name+'-attempt'+str(attempt)+'.log');attempt+=1
        call([ISAAC,str(HERE/'render.py'),str(run),'--gpu',str(device),'--camera',camera,
              '--output-name',name,'--video-fps',fps],log,device)
        if not (run/name/'verification.json').exists():raise RuntimeError('Missing completed camera verification: '+str(run/name))


def export_one(run,device=0):
    if not (run/'replay/verification.json').exists():
        fps=json.loads((run/'pbr_replay/verification.json').read_text())['video']['fps']
        call([PY,'-B',str(CORE/'render_replay.py'),str(run),'--fps',str(int(fps))],BATCH/'reports/logs'/(run.name+'-episode.log'),device)
    call([PY,'-B',str(HERE/'media.py'),'--run',str(run)],BATCH/'reports/logs'/(run.name+'-media.log'),device)


def render_queue(device=0):
    """Claim whole runs so multiple explicit GPUs never render/export one twice."""
    from fixtures_v4.media import current_task_intent
    jobs=[(t,v) for t in TASKS for v in catalog()['tasks'][t]['variants']]
    locks=BATCH/'reports/render_locks';locks.mkdir(exist_ok=True)
    def ready(run):
        return (run/'visual_review_frames.json').exists() and (run/'replay/verification.json').exists()
    while True:
        complete=0;worked=False
        for task,variant in jobs:
            paths=sorted((BATCH/'tasks'/task/variant/'runs').glob('*'));valid=[]
            for run in paths:
                ev=run/'evaluation.json';intent=run/'intent_review.json'
                if ev.exists() and json.loads(ev.read_text()).get('success') and (not intent.exists() or json.loads(intent.read_text()).get('expert_eligible') is not False) and current_task_intent(run,task):valid.append(run)
            if any(ready(run) for run in valid):complete+=1;continue
            if not valid:continue
            run=valid[-1]
            handoff=BATCH/'reports/render_handoff.json'
            if handoff.exists():
                h=json.loads(handoff.read_text())
                if h.get('active') and h['run']==run.name:continue
            with (locks/(run.name+'.lock')).open('a') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:continue  # Another GPU owns this entire run.
                if not ready(run):
                    print('RENDER_START',run.name,'mask',os.environ['CUDA_VISIBLE_DEVICES'],flush=True)
                    render_one(run,device);export_one(run,device)
                    print('VIDEO_READY',run.name,flush=True);worked=True
            if worked:break
        if complete==len(jobs):print('ALL_MEDIA_READY',complete,flush=True);return
        if not worked:time.sleep(15)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['build','preflight','run','render','export','verify','publish','all'],default='all')
    parser.add_argument('--task',choices=TASKS,action='append');parser.add_argument('--variants',nargs='+',default=['v001'])
    parser.add_argument('--device',type=int,choices=[0,1],default=0);parser.add_argument('--workers',type=int,choices=[1,2],default=1)
    args=parser.parse_args();environment(args.device)
    if args.stage in ('preflight','run','all') and os.environ['CUDA_VISIBLE_DEVICES'] not in ('0,1','1','2,3','4','5','6'):raise ValueError('Physical tasks use explicit GPUs 0,1, 1, 2,3, 4, 5 or 6')
    if args.workers>len(os.environ['CUDA_VISIBLE_DEVICES'].split(',')):raise ValueError('Workers exceed explicitly visible GPUs')
    jobs=[(task,variant) for variant in args.variants for task in (args.task or TASKS)]
    def process(index,task,variant):
        device=(index%2) if args.workers==2 else args.device
        from fixtures_v4.build_scenes import build
        if args.stage=='build':return str(build(task,variant))
        if args.stage=='preflight':return str(preflight(task,variant,device))
        run=run_one(task,variant,device) if args.stage in ['run','all'] else latest_run(task,variant)
        if run is None:raise ValueError('No run for '+task+'/'+variant)
        if args.stage in ['render','all']:
            if args.stage=='all' and not json.loads((run/'evaluation.json').read_text())['success']:return str(run)
            render_one(run,device)
        if args.stage in ['export','all']:export_one(run,device)
        if args.stage=='verify':call([PY,'-B',str(HERE/'verify.py'),str(run)],BATCH/'reports/logs'/(run.name+'-delivery.log'),device)
        if args.stage=='publish':call([BACKEND,'-B',str(CORE/'publish.py'),'--run',str(run)],BATCH/'reports/logs'/(run.name+'-publication.log'),device)
        return str(run)
    # A parent and its retrieval stay in one queue; all variants use new directories.
    chains=[['hang_on_rod','retrieve_from_rod'],['place_in_basket','retrieve_from_basket'],['cover_box']]
    groups=[[(t,v) for v in args.variants for t in chain if not args.task or t in args.task] for chain in chains]
    groups=[g for g in groups if g]
    def worker(offset):
        results=[]
        for group in groups[offset::args.workers]:
            for task,variant in group:results.append(process(offset,task,variant))
        return results
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=[x for future in [pool.submit(worker,i) for i in range(args.workers)] for x in future.result()]
    print('BATCH_STAGE_COMPLETE',args.stage,json.dumps(results),flush=True)


if __name__=='__main__':main()
