"""Bounded parameter trials after matched physical and evidence gates."""
import argparse,json,os,subprocess,concurrent.futures
from pathlib import Path
from foundation import verify,sha
ROOT=Path(__file__).resolve().parent;DATA=ROOT.parents[1]/'data/expert_demos/curobo-cloth-v1'
def main():
    p=argparse.ArgumentParser();p.add_argument('--positive',required=True);p.add_argument('--negative',required=True)
    p.add_argument('--tasks',default='corner_lift');p.add_argument('--materials',default='light,medium,heavy');p.add_argument('--initials',default='nominal,shift_left,shift_right')
    p.add_argument('--repetitions',type=int,default=3);p.add_argument('--gpus',default='1,2,4,5');p.add_argument('--name',required=True);a=p.parse_args()
    gate=verify(a.positive,a.negative)
    for name,digest in gate['code_hashes'].items():
        if sha(ROOT/name)!=digest:raise ValueError('Execution code changed since foundation: '+name)
    tasks=a.tasks.split(',');materials=a.materials.split(',');initials=a.initials.split(',');gpus=a.gpus.split(',')
    if any(x not in ['corner_lift','smooth'] for x in tasks):raise ValueError('Task has no qualified recipe')
    if not 1<=a.repetitions<=3 or '7' in gpus:raise ValueError('Unsafe repetition/GPU selection')
    out=DATA/'batches'/a.name;out.mkdir(parents=True,exist_ok=False);(out/'foundation_gate.json').write_text(json.dumps(gate,indent=2))
    configs=[(task,m,i) for task in tasks for m in materials for i in initials]
    queues=[configs[k::len(gpus)] for k in range(len(gpus))]
    def worker(gpu,queue):
        rows=[]
        for task,material,initial in queue:
            for rep in range(a.repetitions):
                ident=f'{task}-{material}-{initial}-r{rep+1:02d}';run=out/ident
                env=os.environ.copy();env['CLOTH_GPU']=gpu
                command=['python3','-B',str(ROOT/'launch.py'),'runner.py','--task',task,'--material',material,'--initial',initial,
                         '--seed',str(194731+rep),'--pregrasp-start','--output',str(run)]
                with (out/(ident+'.log')).open('x') as log:
                    result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
                evaluator=subprocess.run(['/data/zhanghejun/miniconda3/envs/genesis/bin/python','-B',str(ROOT/'evaluate.py'),str(run)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                (out/(ident+'.evaluation.log')).write_text(evaluator.stdout)
                e=json.loads((run/'evaluation.json').read_text()) if evaluator.returncode==0 else {'success':False,'failed_gates':['evaluator_error']}
                row={'id':ident,'run':str(run),'task':task,'material':material,'initial':initial,'repetition':rep+1,'gpu':gpu,
                     'returncode':result.returncode,'success':e['success'],'failed_gates':e['failed_gates']}
                rows.append(row);print('TRIAL',json.dumps(row),flush=True)
                (out/('worker_'+gpu+'.json')).write_text(json.dumps(rows,indent=2))
                # Do not spend three repeats on a configuration whose first mechanics fail.
                if not e['success']:break
        return rows
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(gpus)) as pool:
        results=list(pool.map(lambda x:worker(*x),zip(gpus,queues)))
    rows=[x for group in results for x in group];report={'requested_configs':len(configs),'requested_runs':len(configs)*a.repetitions,'attempted':len(rows),
        'physics_successes':sum(x['success'] for x in rows),'expert_ready':0,'note':'Successes still require replay and publication. Independent process repetitions are not assumed statistically independent.','runs':rows}
    (out/'report.json').write_text(json.dumps(report,indent=2));print('BATCH_COMPLETE',json.dumps(report),flush=True)
if __name__=='__main__':main()
