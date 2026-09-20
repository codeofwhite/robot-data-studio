"""Independent final linkage audit over saved trajectory, videos and Canonical Episode."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();run=a.run.resolve()
 project=Path(__file__).resolve().parents[3];sys.path[:0]=[str(project/'packages/robot-data-contracts/src'),str(project/'expert_demos/curobo_cloth_v1')]
 from robot_data_contracts.validation import inspect_episode
 from scene_adapter import verify_scene_sources
 from render_replay import exact_frames
 cfg=json.loads((run/'config.json').read_text());ev=json.loads((run/'evaluation.json').read_text());vr=json.loads((run/'visual_review.json').read_text())
 assert ev['success'] and vr['passed'] and vr['assisted_grasp_disclosed']
 for name,digest in ev['input_sha256'].items():assert sha(run/name)==digest,name
 if ev.get('evaluator_source_sha256'):
  archive=Path(ev['evaluator_source_root']);assert archive.resolve().is_relative_to(run)
  for name,digest in ev['evaluator_source_sha256'].items():assert sha(archive/name)==digest,name
 verify_scene_sources(cfg['scene_binding'])
 manifest=json.loads((run/'source_manifest.json').read_text())
 for name,digest in manifest['code'].items():assert sha(run/'source_snapshot'/name)==digest,name
 for name,digest in manifest['physical_assets'].items():assert sha(run/'physical_scene'/name)==digest,name
 for name,digest in manifest['shared_assets'].items():assert sha(project/'expert_demos/curobo_cloth_v1'/name)==digest,name
 with np.load(run/'trajectory.npz') as data:arrays={k:data[k] for k in data.files}
 rows={x['tick']:x for x in map(json.loads,(run/'physics.jsonl').read_text().splitlines())}
 fixture=None
 if cfg.get('task_spec',{}).get('rod_clamp',{}).get('enabled'):
  from fixtures_v4.metrics import fixture_trace_audit
  events=json.loads((run/'events.json').read_text())
  fixture_rows=list(map(json.loads,(run/'fixture_constraints.jsonl').read_text().splitlines()))
  grips=list(map(json.loads,(run/'grasp_constraints.jsonl').read_text().splitlines()))
  fixture=fixture_trace_audit(cfg,events,fixture_rows,grips,arrays['tick'],arrays['cloth_vertices'],physics_rows=rows)
  fixture['trace_sha256']=sha(run/'fixture_constraints.jsonl')
  assert vr.get('fixture_assistance_disclosed') is True
  assert vr.get('fixture_constraints_sha256')==fixture['trace_sha256']
 max_error=0.
 for i,tick in enumerate(arrays['tick']):
  if tick==0:continue
  state=rows[int(tick)]['state_after_step'][0]
  q=np.asarray(state['joints']+state['fingers']);error=float(np.max(np.abs(q-arrays['qpos'][i,0])));max_error=max(max_error,error)
 assert max_error<1e-6,max_error
 views={}
 for name in ['pbr_replay','pbr_overhead']:
  v=json.loads((run/name/'verification.json').read_text());assert not v['preview_only'] and v['cloth_vertices_exact']
  assert v['trajectory_sha256']==sha(run/'trajectory.npz')
  if fixture:
   assert v['fixture_assistance']['trace_sha256']==fixture['trace_sha256']
   assert v['fixture_assistance']['configuration']==cfg['task_spec']['rod_clamp']
   assert v['fixture_assistance']['free_bare_rod_hanging_claimed'] is False
   assert v['fixture_assistance']['indicator_source_sha256']==sha(run/(name+'_render_code')/'fixture_render.py')
   assert sha(run/(name+'_render_code')/'fixture_render.py')==sha(run/'source_snapshot/fixtures_v4/fixtures.py')
   row_by_tick={r['tick']:r for r in fixture_rows}
   for frame in v['frame_map']:
    r=row_by_tick.get(frame['tick'],{'active':False})
    assert frame['fixture_active']==r['active']
    assert frame['fixture_row_sha256']==hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()
  assert v['video']['sha256']==sha(run/name/'front.mp4')
  expected=exact_frames(arrays['tick'],int(arrays['tick'][-1]),cfg['dt'],v['video']['fps'])
  assert [x['tick'] for x in v['frame_map']]==[x['tick'] for x in expected]
  for row in v['frame_map']:assert sha(run/name/row['image_path'])==row['image_sha256']
  views[name]={'frames':len(v['frame_map']),'video_sha256':v['video']['sha256'],'ticks':[x['tick'] for x in v['frame_map']]}
 # Camera clocks may differ (5 Hz hero, 2 Hz overhead). Each clock has already
 # been checked independently against exact recorded physical snapshots.
 assert all(set(v['ticks']).issubset(set(map(int,arrays['tick']))) for v in views.values())
 assert views['pbr_overhead']['ticks'][0]==views['pbr_replay']['ticks'][0]
 assert vr['trajectory_sha256']==sha(run/'trajectory.npz') and vr['video_sha256']==views['pbr_replay']['video_sha256']
 replay=json.loads((run/'replay/verification.json').read_text());ep=Path(replay['episode_path'])
 for name,digest in replay['episode_sha256'].items():assert sha(ep/name)==digest,name
 inspect_episode(ep/'manifest.json',engine_id='genesis')
 em=json.loads((ep/'manifest.json').read_text());metadata=em['scene']['parameters']
 assert f"{cfg['dt']*1000:g}ms" in metadata['action_semantics']
 assert metadata['control_rate_hz']==1/cfg['dt']
 if fixture:assert metadata['config']['task_spec']['rod_clamp']==cfg['task_spec']['rod_clamp']
 result={'passed':True,'trajectory_sha256':sha(run/'trajectory.npz'),'scene':cfg['scene_binding']['scene'],'physics_ticks':int(arrays['tick'][-1]),'snapshots':len(arrays['tick']),'max_recorded_joint_position_difference':max_error,'views':{k:{x:y for x,y in v.items() if x!='ticks'} for k,v in views.items()},'native_episode':str(ep),'native_episode_files':len(replay['episode_sha256']),'assisted_grasp':cfg['assisted_grasp'],'reviewer':'SELF_REVIEWED_PROVISIONAL','audit_code_sha256':sha(__file__)}
 if fixture:result['fixture_assistance']=fixture
 (run/'delivery_verification_source.py').write_bytes(Path(__file__).read_bytes());(run/'delivery_verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
