"""Fail-closed gate for parameter batches."""
import json,hashlib
from pathlib import Path
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(positive,negative):
    p,n=Path(positive),Path(negative)
    pe,ne=[json.loads((r/'evaluation.json').read_text()) for r in [p,n]]
    pc,nc=[json.loads((r/'config.json').read_text()) for r in [p,n]]
    if pe['success'] is not True:raise ValueError('Positive grasp is not verified')
    if ne['success'] is not False or not ne['gates'].get('grasp_phases_complete') or not ne['gates'].get('no_halt'):raise ValueError('Negative control must complete the task and physically fail, not merely crash')
    if ne['gates'].get('physical_lift') or ne['gates'].get('loaded_gripper_gap'):raise ValueError('No-close control did not demonstrate rejection of grasp/lift')
    if pc.pop('negative_control') is not False or nc.pop('negative_control') is not True or pc!=nc:raise ValueError('Controls are not exactly matched')
    pm,nm=[json.loads((r/'source_manifest.json').read_text()) for r in [p,n]]
    modules=['runner.py','planner.py','collision_model.py','profiles.py','scene_adapter.py','record_episode.py',
             'runtime/scene.py','runtime/robot.py','runtime/safety.py','runtime/ipc_state_sync.py','runtime/ipc_axis_compat.py','runtime/prepare_assets.py']
    for name in modules:
        if pm['code'][name]!=nm['code'][name]:raise ValueError('Control code differs: '+name)
    for r,e in [(p,pe),(n,ne)]:
        for name,digest in e['input_sha256'].items():
            if sha(r/name)!=digest:raise ValueError('Evidence changed: '+str(r/name))
        v=json.loads((r/'replay/verification.json').read_text())
        if not v['native_episode_valid'] or not v['exact_frame_ticks'] or v['trajectory_sha256']!=sha(r/'trajectory.npz'):raise ValueError('Replay evidence invalid')
    return {'passed':True,'positive':str(p),'negative':str(n),'evaluation_hashes':[sha(r/'evaluation.json') for r in [p,n]],'code_hashes':{x:pm['code'][x] for x in modules},'scope':'Permission to attempt synthetic variations, not a robustness claim.'}
