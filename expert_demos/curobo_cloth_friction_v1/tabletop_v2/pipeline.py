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

HERE=Path(__file__).resolve().parent;CORE=HERE.parent;PROJECT=CORE.parents[1]
DATA=PROJECT/'data/expert_demos/curobo-cloth-v1';BATCH=DATA/'tabletop_v2'
PY='/data/zhanghejun/miniconda3/envs/genesis/bin/python'
PLANNER='/data/zhanghejun/SIMPLE/.venv/bin/python'
ISAAC='/data/zhanghejun/isaacsim_6.0.1/python.sh'
BACKEND=str(PROJECT/'backend/.venv/bin/python')
sys.path.insert(0,str(CORE))
from tabletop_v2 import TASKS,catalog


def environment(device=0):
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='0,1':raise RuntimeError('Set CUDA_VISIBLE_DEVICES=0,1')
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='0,1',CUDA_LAUNCH_BLOCKING='0',PYTHONDONTWRITEBYTECODE='1',
             PYOPENGL_PLATFORM='egl',EGL_DEVICE_ID=str(device),OMP_NUM_THREADS='4')
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
    from tabletop_v2.build_scenes import build
    import numpy as np
    from scipy.spatial.transform import Rotation
    build(task,variant)
    out=BATCH/'diagnostics'/task/variant
    out.mkdir(parents=True,exist_ok=True)
    plan=out/'initialization_plan.json'
    if plan.exists():return plan
    prepared=out/'prepared'
    scene='ttv2_'+task+'_'+variant
    if not prepared.exists():
        call([PY,'-B',str(CORE/'runner.py'),'--scene',scene,'--task',task,'--visual-demo-profile',
              '--physics-device',str(device),'--prepare-only','--output',str(prepared)],out/'prepare.log',device)
    cfg=json.loads((prepared/'config.json').read_text());topology=json.loads(Path(cfg['scene_binding']['topology_path']).read_text())
    primary=cfg['task_spec']['primary_corner'];point=np.asarray(topology['initial_vertices'][primary])
    hover=point.copy();hover[2]=max(.96,point[2]+.16)
    q=(Rotation.from_euler('z',90,degrees=True)*Rotation.from_euler('x',180,degrees=True)).as_quat()[[3,0,1,2]].tolist()
    request=dict(q=cfg['home'][:7],tcp_world=hover.tolist(),quaternion_wxyz=q)
    (out/'request.json').write_text(json.dumps(request,indent=2))
    raw=out/'planner_result.json'
    call([PLANNER,'-B',str(CORE/'planner.py'),'--config',str(prepared/'config.json'),
          '--preflight',str(raw),'--request',str(out/'request.json')],out/'planner.log',device)
    result=json.loads(raw.read_text());assert result['success']
    result['grasp_seed']=dict(vertex_index=primary,quaternion_wxyz=q,approach_offset_m=[0,0,.12])
    plan.write_text(json.dumps(result,indent=2));return plan


def latest_run(task,variant):
    root=BATCH/'tasks'/task/variant/'runs'
    paths=sorted(root.glob('*')) if root.exists() else []
    return paths[-1] if paths else None


def run_one(task,variant,device=0):
    plan=preflight(task,variant,device)
    seed=catalog()['seed'];stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dt%H%M%S')
    ident='ttv2-'+task.replace('_','-')+'-'+variant+'-'+stamp
    run=BATCH/'tasks'/task/variant/'runs'/ident;run.parent.mkdir(parents=True,exist_ok=True)
    log=BATCH/'reports/logs'/(ident+'.log')
    print('RUN_START',ident,'physics_device',device,flush=True)
    returncode=call([PY,'-B','-u',str(CORE/'runner.py'),'--scene','ttv2_'+task+'_'+variant,'--task',task,
          '--scene-hover-plan',str(plan),'--visual-demo-profile','--physics-device',str(device),
          '--seed',str(seed),'--output',str(run)],log,device,allowed_returncodes=(0,2))
    if returncode==2 and not (run/'run_summary.json').exists():
        raise RuntimeError('Runner returned 2 without a saved summary; see '+str(log))
    provenance=BATCH/'reports/environment.json'
    if provenance.exists():
        value=json.loads(provenance.read_text());value.update(run=ident,physics_cuda_device=device)
        (run/'environment_provenance.json').write_text(json.dumps(value,indent=2))
    (run/'launch.json').write_text(json.dumps(dict(log=str(log),CUDA_VISIBLE_DEVICES='0,1',physics_device=device,initialization_plan=str(plan),runner_returncode=returncode),indent=2))
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


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['build','preflight','run','render','export','verify','publish','all'],default='all')
    parser.add_argument('--task',choices=TASKS,action='append');parser.add_argument('--variants',nargs='+',default=['v001'])
    parser.add_argument('--device',type=int,choices=[0,1],default=0);parser.add_argument('--workers',type=int,choices=[1,2],default=1)
    args=parser.parse_args();environment(args.device)
    jobs=[(task,variant) for variant in args.variants for task in (args.task or TASKS)]
    def process(index,task,variant):
        device=(index%2) if args.workers==2 else args.device
        from tabletop_v2.build_scenes import build
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
    # Each worker owns one GPU. Queues keep the ownership stable even when
    # different task durations would otherwise reshuffle executor workers.
    def worker(offset):
        results=[]
        for index in range(offset,len(jobs),args.workers):
            task,variant=jobs[index];results.append(process(index,task,variant))
        return results
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=[x for future in [pool.submit(worker,i) for i in range(args.workers)] for x in future.result()]
    print('BATCH_STAGE_COMPLETE',args.stage,json.dumps(results),flush=True)


if __name__=='__main__':main()
