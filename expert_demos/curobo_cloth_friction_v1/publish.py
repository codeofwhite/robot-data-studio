"""Publish immutable configurations and evidence. Failed runs remain failed."""
import argparse,json,hashlib,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1];DATA=PROJECT/'data/expert_demos/curobo-cloth-v1';SOURCE='curobo-cloth-v1'
sys.path[:0]=[str(PROJECT/'backend/src'),str(PROJECT/'packages/robot-data-contracts/src')]
from robot_data_contracts.asset import AssetDraft
from robot_data_studio.services.asset_service import AssetRegistry
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def artifact(path,role):
    p=Path(path);return {'source_id':SOURCE,'path':p.relative_to(DATA).as_posix(),'role':role,'sha256':sha(p),'size_bytes':p.stat().st_size}
def draft(ident,kind,name,data,artifacts,refs=None,tags=None):
    return AssetDraft(asset_id=ident,kind=kind,name=name,data=data,artifacts=artifacts,references=refs or [],
      engines=['genesis'],tags=['cloth','curobo','expert-data']+(tags or []),description='真实状态证据与候选配置分开保存；SELF_REVIEWED_PROVISIONAL。',change_note='新增布料专家数据 v1，保留失败与不可执行状态。')
def ref(ident,role):return {'asset_id':ident,'version':1,'role':role}
def matched_scene_configuration(config):
    """Normalize only this run's artifact root, including component-map keys."""
    binding=config.get('scene_binding')
    if not binding:raise ValueError('Matched original-scene gate requires a scene binding')
    root=Path(binding['snapshot_root']).parent
    roots={root.as_posix(),(DATA/root).resolve().as_posix()}
    def normalize(value):
        if isinstance(value,str):
            for prefix in sorted(roots,key=len,reverse=True):
                if value==prefix or value.startswith(prefix+'/'):return '<RUN>'+value[len(prefix):]
            return value
        if isinstance(value,list):return [normalize(x) for x in value]
        if isinstance(value,dict):return {normalize(k):normalize(v) for k,v in value.items()}
        return value
    return normalize({k:v for k,v in config.items() if k!='negative_control'})

def verify_scene_pair(positive,negative):
    """Require a successful contact trial and a matched, completed no-close failure."""
    from scene_adapter import verify_scene_sources
    runs=[Path(positive).resolve(),Path(negative).resolve()]
    configs=[json.loads((r/'config.json').read_text()) for r in runs]
    evaluations=[json.loads((r/'evaluation.json').read_text()) for r in runs]
    pc,nc=configs;pe,ne=evaluations
    if pc.get('negative_control') is not False or nc.get('negative_control') is not True:raise ValueError('Expected positive and no-close controls')
    if matched_scene_configuration(pc)!=matched_scene_configuration(nc):raise ValueError('Original-scene controls are not matched')
    if pe['success'] is not True or not pe['gates'] or not all(pe['gates'].values()):raise ValueError('Positive grasp is not verified')
    if ne['success'] is not False or not ne['gates'].get('grasp_phases_complete') or not ne['gates'].get('no_halt'):raise ValueError('No-close control must finish without a halt')
    if ne['gates'].get('physical_lift') is not False or ne['gates'].get('loaded_gripper_gap') is not False:raise ValueError('No-close control did not reject physical grasp/lift')
    allowed_negative_failures={'physical_lift','loaded_gripper_gap','release_drop'}
    if any(not value and key not in allowed_negative_failures for key,value in ne['gates'].items()):raise ValueError('Negative control has unrelated failed gates')
    modules=['runner.py','planner.py','collision_model.py','profiles.py','scene_adapter.py','record_episode.py',
        'evaluate.py','runtime/evaluate.py','runtime/table_geometry.py',
        'runtime/scene.py','runtime/robot.py','runtime/safety.py','runtime/ipc_state_sync.py','runtime/ipc_axis_compat.py','runtime/prepare_assets.py']
    manifests=[json.loads((r/'source_manifest.json').read_text()) for r in runs]
    if any(manifests[0]['code'][name]!=manifests[1]['code'][name] for name in modules):raise ValueError('Control code differs')
    if any(manifests[0][family]!=manifests[1][family] for family in ['physical_assets','shared_assets']):raise ValueError('Control physical assets differ')
    evidence=[]
    for run,cfg,evaluation,manifest in zip(runs,configs,evaluations,manifests):
        verify_scene_sources(cfg['scene_binding'])
        if not evaluation.get('input_sha256'):raise ValueError('Missing evaluation input hashes')
        for name,digest in evaluation['input_sha256'].items():
            if sha(run/name)!=digest:raise ValueError('Evaluation input changed: '+name)
        for name in modules:
            if sha(run/'source_snapshot'/name)!=manifest['code'][name]:raise ValueError('Archived control code changed: '+name)
        for name,digest in manifest['physical_assets'].items():
            if sha(run/'physical_scene'/name)!=digest:raise ValueError('Physical asset changed: '+name)
        for name,digest in manifest['shared_assets'].items():
            if sha(ROOT/name)!=digest:raise ValueError('Shared physical asset changed: '+name)
        replay=json.loads((run/'replay/verification.json').read_text());pbr=json.loads((run/'pbr_replay/verification.json').read_text())
        if not replay['native_episode_valid'] or not replay['exact_frame_ticks']:raise ValueError('Canonical replay is not verified')
        episode=Path(replay['episode_path']);episode_hashes=replay.get('episode_sha256')
        if not episode_hashes or not episode.is_relative_to(run):raise ValueError('Missing local Canonical Episode hashes')
        for name,digest in episode_hashes.items():
            if sha(episode/name)!=digest:raise ValueError('Canonical Episode changed: '+name)
        from robot_data_contracts.validation import inspect_episode
        inspect_episode(episode/'manifest.json',engine_id='genesis')
        for report in [replay,pbr]:
            if report['trajectory_sha256']!=sha(run/'trajectory.npz') or report.get('original_scene_loaded') is not True or report.get('scene')!=cfg['scene_binding']['scene'] or report.get('scene_binding_sha256')!=sha(run/'scene_binding.json'):raise ValueError('Video is not bound to the original scene trajectory')
        if pbr['preview_only'] or not pbr['cloth_vertices_exact']:raise ValueError('PBR replay is not exact')
        if pbr.get('stage_meters_per_unit')!=1. or pbr.get('stage_up_axis')!='Z':raise ValueError('Expert replay must explicitly preserve metre Z-up stage metadata')
        for camera,info in replay['videos'].items():
            if sha(run/'replay'/(camera+'.mp4'))!=info['sha256']:raise ValueError('Canonical video changed')
        if sha(run/'pbr_replay/front.mp4')!=pbr['video']['sha256']:raise ValueError('PBR video changed')
        for row in pbr['frame_map']:
            if sha(run/'pbr_replay'/row['image_path'])!=row['image_sha256']:raise ValueError('PBR image changed')
        evidence.append({name:sha(run/name) for name in ['evaluation.json','replay/verification.json','pbr_replay/verification.json','scene_binding.json','source_manifest.json']})
    return {'passed':True,'positive':str(runs[0]),'negative':str(runs[1]),'scene':pc['scene_binding']['scene'],
        'evidence_sha256':evidence,'gate_code_sha256':sha(Path(__file__)),
        'code_hashes':{name:manifests[0]['code'][name] for name in modules},
        'scope':'This matched pair only; not a dual-arm, dexterous-hand, robustness or real-robot claim.'}
def publish_catalog(registry):
    from profiles import MATERIALS
    out=DATA/'catalog';rows=json.loads((out/'candidates.json').read_text())['candidates'];result=[]
    materials=out/'materials';materials.mkdir(exist_ok=True)
    for name,m in MATERIALS.items():
        p=materials/(name+'.json');value={'id':name,'synthetic':True,'measured_real_fabric':False,**m}
        if not p.exists():p.write_text(json.dumps(value,indent=2))
        d=draft('MAT-curobo-cloth-'+name,'material','合成布料参数 '+name,value,[artifact(p,'parameters')],tags=['synthetic'])
        record,created=registry.publish(d,expected_version=0,idempotent=True);result.append(record)
    instances=out/'instances';instances.mkdir(exist_ok=True)
    for row in rows:
        p=instances/(row['id']+'.json')
        if not p.exists():p.write_text(json.dumps(row,ensure_ascii=False,indent=2))
        d=draft('CFG-curobo-cloth-'+row['id'].replace('_','-'),'config','布料候选 '+row['id'],
          {'status':row['status'],'task':row['task'],'profile':row['profile'],'criteria':row['criteria'],'physics_verified':False,
           'note':'这是冻结的实验候选配置。真实运行与结果另存 VAL 记录，不能据此算成功示范。'},
          [artifact(p,'configuration')],[ref('MAT-curobo-cloth-'+row['material'],'material')],['candidate'])
        record,created=registry.publish(d,expected_version=0,idempotent=True);result.append(record)
    return result
def publish_run(registry,run,negative_run=None):
    run=Path(run).resolve();evaluation=json.loads((run/'evaluation.json').read_text());cfg=json.loads((run/'config.json').read_text())
    for name,digest in evaluation.get('input_sha256',{}).items():
        if sha(run/name)!=digest:raise ValueError('Evaluation input changed: '+name)
    available=evaluation['available'];success=evaluation['success']
    replay=run/'replay/verification.json';verified=replay.exists() and json.loads(replay.read_text()).get('native_episode_valid') is True
    if replay.exists():
        video_report=json.loads(replay.read_text())
        if video_report['trajectory_sha256']!=sha(run/'trajectory.npz'):raise ValueError('Replay belongs to a different trajectory')
        for camera,info in video_report['videos'].items():
            if sha(run/'replay'/(camera+'.mp4'))!=info['sha256']:raise ValueError('Video changed: '+camera)
    foundation=DATA/'foundation_gate.json'
    foundation_passed=foundation.exists() and json.loads(foundation.read_text()).get('passed') is True
    pbr=run/'pbr_replay/verification.json'
    if pbr.exists():
        pv=json.loads(pbr.read_text())
        if pv['trajectory_sha256']!=sha(run/'trajectory.npz') or pv['preview_only'] or not pv['cloth_vertices_exact']:raise ValueError('Invalid PBR trajectory association')
        if sha(run/'pbr_replay/front.mp4')!=pv['video']['sha256']:raise ValueError('PBR video changed')
    binding=cfg.get('scene_binding')
    scene_gate=None
    if binding:
        # A gate from the historical simplified world cannot qualify an original scene.
        foundation_passed=False
        from scene_adapter import verify_scene_sources
        verify_scene_sources(binding)
        if not replay.exists() or not pbr.exists():raise ValueError('Original scene requires verified PBR video and native Episode')
        for report in [video_report,pv]:
            if report.get('scene')!=binding['scene'] or report.get('scene_binding_sha256')!=sha(run/'scene_binding.json') or report.get('original_scene_loaded') is not True:
                raise ValueError('Evidence does not match the original scene binding')
        for row in pv['frame_map']:
            if sha(run/'pbr_replay'/row['image_path'])!=row['image_sha256']:raise ValueError('Original-scene image changed')
        if negative_run:
            scene_gate=verify_scene_pair(run,negative_run);foundation_passed=True
            gate_path=run/'scene_foundation_gate.json'
            if gate_path.exists() and json.loads(gate_path.read_text())!=scene_gate:raise ValueError('Existing scene gate differs')
            if not gate_path.exists():gate_path.write_text(json.dumps(scene_gate,indent=2))
            gate_code=run/'scene_foundation_code.py'
            if gate_code.exists() and sha(gate_code)!=scene_gate['gate_code_sha256']:raise ValueError('Archived scene gate code differs')
            if not gate_code.exists():gate_code.write_bytes(Path(__file__).read_bytes())
    elif negative_run:raise ValueError('Matched scene controls require --scene evidence')
    ident=run.name.replace('_','-')
    refs=[ref('MAT-curobo-cloth-'+cfg['material_provenance']['preset'],'material')]
    if not binding and cfg['task_id']!='hold':
        candidate='CFG-curobo-cloth-'+(cfg['task_id']+'-'+cfg['material_provenance']['preset']+'-'+next(k for k,v in __import__('profiles').INITIALS.items() if v==cfg['initial_variant'])).replace('_','-')
        refs=[ref(candidate,'run_configuration')]
    if binding:
        # Legacy candidates encode a different table/cloth; never associate their CFG with this run.
        refs=[{'asset_id':binding['scene']['asset_id'],'version':binding['scene']['version'],'role':'executed_scene'},
              ref('MAT-curobo-cloth-'+cfg['material_provenance']['preset'],'material')]
    files=[('evaluation.json','evaluation'),('config.json','configuration'),('trajectory.npz','trajectory'),('physics.jsonl','control_trace'),('events.json','events'),('source_manifest.json','provenance'),('environment_provenance.json','software_environment'),('contact_audit.json','contact_audit'),('fk_audit.json','fk_audit'),('trajectory_view.html','standalone_trajectory_viewer'),('trajectory_view.json','trajectory_viewer_verification')]
    for view in ['pbr_replay','pbr_overhead']:
        files.extend([(view+'_cache_invocation.json','renderer_invocation'),
                      (view+'_cache_source.py','renderer_entrypoint')])
    artifacts=[artifact(run/name,role) for name,role in files if (run/name).exists()]
    for name,role in [('README.md','data_guide'),('delivery_verification.json','delivery_verification')]:
        if (run/name).exists():artifacts.append(artifact(run/name,role))
    if (run/'overview_4x.json').exists():
        overview=json.loads((run/'overview_4x.json').read_text())
        if overview['source_trajectory_sha256']!=sha(run/'trajectory.npz') or overview['video_sha256']!=sha(run/'overview_4x.mp4'):
            raise ValueError('Overview video changed or belongs to another trajectory')
        if overview['source_video_sha256']!=sha(run/'pbr_replay/front.mp4'):raise ValueError('Overview source video changed')
        artifacts.extend([artifact(run/'overview_4x.mp4','video_overview_4x'),artifact(run/'overview_4x.json','overview_provenance')])
    if verified:
        episode=Path(video_report['episode_path']).resolve()
        if not episode.is_relative_to(run):raise ValueError('Canonical Episode must belong to this run')
        episode_hashes=video_report.get('episode_sha256',{})
        for name,role in [('manifest.json','canonical_episode_manifest'),('trajectory.npz','canonical_episode_trajectory')]:
            path=episode/name
            if sha(path)!=episode_hashes.get(name):raise ValueError('Canonical Episode changed: '+name)
            artifacts.append(artifact(path,role))
    if binding:artifacts.append(artifact(run/'scene_binding.json','scene_provenance'))
    if scene_gate:artifacts.append(artifact(run/'scene_foundation_gate.json','matched_contact_control'))
    if (run/'trajectory_view.html').exists():
        view=json.loads((run/'trajectory_view.json').read_text())
        for field,name in [('source_trajectory_sha256','trajectory.npz'),('source_physics_sha256','physics.jsonl'),('viewer_sha256','trajectory_view.html')]:
            if view[field]!=sha(run/name):raise ValueError('Interactive replay input changed: '+name)
        if view.get('source_constraint_sha256') and view['source_constraint_sha256']!=sha(run/'grasp_constraints.jsonl'):raise ValueError('Interactive replay assistance trace changed')
    for camera in ['front','top','wrist']:
        p=run/'replay'/(camera+'.mp4')
        if p.exists():artifacts.append(artifact(p,'video_'+camera))
    if replay.exists():artifacts.append(artifact(replay,'frame_mapping'))
    previews=sorted((run/'replay').glob('front_*.png'))
    if previews:artifacts.append(artifact(previews[len(previews)//2],'preview'))
    if pbr.exists():
        artifacts.extend([artifact(pbr,'pbr_verification'),artifact(run/'pbr_replay/front.mp4','video_pbr')])
        previews=sorted((run/'pbr_replay').glob('front_*.png'))
        if previews:artifacts.append(artifact(previews[len(previews)//2],'pbr_preview'))
    for view in ['pbr_detail','pbr_grasp','pbr_overhead']:
        if not (run/view).exists():continue
        view_report=run/view/'verification.json';vr=json.loads(view_report.read_text())
        if vr['preview_only'] or not vr['cloth_vertices_exact'] or vr['trajectory_sha256']!=sha(run/'trajectory.npz'):raise ValueError('Invalid additional camera replay: '+view)
        if binding and (vr.get('scene')!=binding['scene'] or vr.get('scene_binding_sha256')!=sha(run/'scene_binding.json') or not vr.get('original_scene_loaded')):raise ValueError('Additional camera belongs to another scene')
        if sha(run/view/'front.mp4')!=vr['video']['sha256']:raise ValueError('Additional camera video changed')
        for row in vr['frame_map']:
            if sha(run/view/row['image_path'])!=row['image_sha256']:raise ValueError('Additional camera image changed')
        artifacts.extend([artifact(view_report,view+'_verification'),artifact(run/view/'front.mp4','video_'+view)])
    assisted=cfg.get('assisted_grasp',{}).get('enabled',False)
    review_path=run/'visual_review.json';review=json.loads(review_path.read_text()) if review_path.exists() else {}
    assisted_reviewed=False
    if assisted:
        for name,role in [('grasp_constraints.jsonl','assisted_grasp_trace'),('task_progress.json','task_progress'),('visual_review.json','visual_review')]:
            if (run/name).exists():artifacts.append(artifact(run/name,role))
        if review:
            if review.get('trajectory_sha256')!=sha(run/'trajectory.npz') or review.get('video_sha256')!=sha(run/'pbr_replay/front.mp4'):raise ValueError('Visual review does not match this trajectory and video')
            assisted_reviewed=review.get('passed') is True and review.get('assisted_grasp_disclosed') is True
    publication_source=run/'publication_code'/sha(Path(__file__))[:12]/'publish.py'
    publication_source.parent.mkdir(parents=True,exist_ok=True)
    if not publication_source.exists():publication_source.write_bytes(Path(__file__).read_bytes())
    if sha(publication_source)!=sha(Path(__file__)):raise ValueError('Archived publication code changed')
    artifacts.append(artifact(publication_source,'publication_code'))
    bundle=run/'evidence.zip'
    if not bundle.exists():
        with zipfile.ZipFile(bundle,'x',zipfile.ZIP_DEFLATED,compresslevel=2) as z:
            for p in sorted(run.rglob('*')):
                if p.is_file() and p!=bundle:z.write(p,p.relative_to(run))
            shared=ROOT/'runtime/upstream_assets'
            for p in sorted(shared.rglob('*')):
                if p.is_file():z.write(p,Path('shared_assets')/p.relative_to(shared))
    artifacts.append(artifact(bundle,'evidence_bundle'))
    eligible=success and verified and foundation_passed and cfg['task_id']!='hold' and not cfg['negative_control']
    if assisted:eligible=bool(success and verified and pbr.exists() and assisted_reviewed)
    data={'outcome':'passed' if success else ('failed' if available else 'unavailable'),'engine_id':'genesis',
      'evaluator_version':evaluation['version'],'scope':'true-contact cloth task / recorded-state evidence','metrics':evaluation['metrics'],
      'failed_gates':evaluation['failed_gates'],'task':cfg['task_id'],'expert_eligible':eligible,'video_verified':verified,
      'negative_control':cfg['negative_control'],'foundation_passed':foundation_passed,'pbr_verified':pbr.exists(),'review_status':'SELF_REVIEWED_PROVISIONAL',
      'limitation':'Synthetic material. Single run evidence, not a robustness or real-robot claim.'}
    if assisted:data.update(scope='cuRobo assisted-grasp cloth demonstration / recorded FEM state evidence',
        expert_type='scripted_assisted_simulation',grasp_assistance=cfg['assisted_grasp'],pure_contact_grasp_verified=False,
        visual_demo_available=bool(pbr.exists()),visual_review_passed=assisted_reviewed,
        visual_limitations=review.get('known_limitations',[]),
        limitation='Explicit local kinematic grasp assistance; not friction-only grasp or hardware evidence. Synthetic material; one demonstrated rollout.')
    if binding:data.update(scene=binding['scene'],active_robot=binding['active_robot'],passive_robots=binding['passive_robots'],
        control_scope=binding['control_scope'],original_scene_loaded=True,source_scene_task=binding['scene_name'],
        full_source_scene_task_verified=False)
    if cfg.get('task_spec',{}).get('batch_id') in ('tabletop_v2','folding_v3','fixtures_v4'):
        data.update(batch_id=cfg['task_spec']['batch_id'],variant_id=cfg['task_spec']['variant_id'],run_id=run.name,task_name=cfg['task_spec']['name'])
    d=draft('VAL-curobo-cloth-'+ident,'validation',('辅助夹持示范 ' if assisted else '布料运行 ')+ident,data,artifacts,refs,['success' if eligible else 'diagnostic']+(['assisted-grasp'] if assisted else []))
    record,_=registry.publish(d,expected_version=0,idempotent=True);return record
def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',action='store_true');p.add_argument('--run',action='append',default=[])
    p.add_argument('--negative-run',help='Completed matched no-close control for one original-scene positive run');a=p.parse_args()
    if a.negative_run and len(a.run)!=1:p.error('--negative-run requires exactly one positive --run')
    registry=AssetRegistry();records=publish_catalog(registry) if a.catalog else []
    records += [publish_run(registry,run,a.negative_run) for run in a.run]
    checks={r.asset_id:registry.integrity(r) for r in records}
    result={'published':len(records),'integrity':checks,'all_current':all(v['status']=='current' for v in checks.values())}
    (DATA/'publication_report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    if not result['all_current']:raise SystemExit(2)
if __name__=='__main__':main()
