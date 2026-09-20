"""Render actual recorded states, exact frame/tick mapping, export native Studio Episode."""
import argparse,json,sys,hashlib,importlib.util
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def exact_frames(ticks,last_command_tick,dt,fps):
    step=1/(dt*fps)
    if abs(step-round(step))>1e-8:raise ValueError('Video frame interval must be an integer number of physics steps')
    mapping={int(t):i for i,t in enumerate(ticks)};rows=[]
    for t in range(0,last_command_tick-round(step)+1,round(step)):
        if t not in mapping:raise ValueError('Missing exact recorded frame tick '+str(t))
        rows.append({'frame':len(rows),'tick':t,'sample':mapping[t],'simulation_time_s':t*dt,'video_time_s':len(rows)/fps,'applied_command_row_tick':t+1})
    return rows
def main():
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--fps',type=int,default=10);a=p.parse_args();run=Path(a.run)
    cfg=json.loads((run/'config.json').read_text());evaluation=json.loads((run/'evaluation.json').read_text())
    with np.load(run/'trajectory.npz') as archive:data={k:archive[k] for k in archive.files}
    commands={r['tick']:r for r in map(json.loads,(run/'physics.jsonl').read_text().splitlines())}
    mapping=exact_frames(data['tick'],int(data['tick'][-1]),cfg['dt'],a.fps)
    out=run/'replay';out.mkdir(exist_ok=False)
    (out/'renderer_source.py').write_bytes(Path(__file__).read_bytes())
    (out/'scene_adapter_source.py').write_bytes((ROOT/'scene_adapter.py').read_bytes())
    binding=cfg.get('scene_binding')
    from PIL import Image
    if binding:
        from scene_adapter import verify_scene_sources
        verify_scene_sources(binding)
        pv=json.loads((run/'pbr_replay/verification.json').read_text())
        if pv.get('scene')!=binding['scene'] or pv.get('scene_binding_sha256')!=sha(run/'scene_binding.json'):
            raise ValueError('PBR replay belongs to a different scene binding')
        if pv['trajectory_sha256']!=sha(run/'trajectory.npz') or pv['preview_only'] or not pv.get('original_scene_loaded'):
            raise ValueError('Original-scene full trajectory replay required')
        if [r['tick'] for r in pv['frame_map']]!=[r['tick'] for r in mapping]:raise ValueError('PBR and Episode frame ticks differ')
        for row in pv['frame_map']:
            if sha(run/'pbr_replay'/row['image_path'])!=row['image_sha256']:raise ValueError('PBR image changed')
        camera_names=['front'];cfg['camera_resolution']=pv['resolution']
        calibration={'front':pv['camera']};calibration['front']['intrinsics']=np.asarray(pv['camera']['intrinsics']).reshape(-1).tolist()
        engine_version='recorded Genesis IPC state; Isaac RTX original-scene image replay'
        sys.path.insert(0,str(ROOT.parents[1]/'packages/robot-data-contracts/src'))
        from robot_data_contracts.franka_writer import FrankaEpisodeWriter
        from robot_data_contracts.validation import inspect_episode
    else:
        sys.path.insert(0,str(ROOT/'runtime'))
        import scene;scene.ROOT=run/'physical_scene'
        import genesis as gs;gs.init(backend=gs.cpu,precision='32',seed=cfg['seed'],logging_level='warning')
        from camera import Cameras
        cams=Cameras(cfg)
        sys.path.insert(0,str(ROOT.parents[1]/'packages/robot-data-contracts/src'))
        from robot_data_contracts.franka_writer import FrankaEpisodeWriter
        from robot_data_contracts.validation import inspect_episode
        first={k:data[k][0] for k in ['tick','qpos','link_poses','cloth_vertices']};cams.sync(first)
        calibration={name:{'intrinsics':scene.array(cam.intrinsics).reshape(-1).tolist(),'camera_to_world':scene.array(cam.transform).tolist(),'axes':'OpenGL +X right +Y up -Z forward'} for name,cam in cams.scene.cameras.items()}
        camera_names=list(cams.scene.cameras);engine_version=getattr(gs,'__version__','unknown')
    metadata={'camera_resolution':cfg['camera_resolution'],'camera_intrinsic_matrices':{k:v['intrinsics'] for k,v in calibration.items()},
       'camera_extrinsics':{k:{'camera_to_world':v['camera_to_world'],'axes':v['axes'],'dynamic':k=='wrist'} for k,v in calibration.items()},
       'source_demo_trajectory':str(run/'trajectory.npz'),'source_sha256':sha(run/'trajectory.npz'),
       'config':cfg,'evaluation_path':str(run/'evaluation.json'),'replay_only':True,
       'camera_timestamp_domain':'simulation seconds reconstructed from exact recorded ticks',
       'control_rate_hz':1/cfg['dt'],'video_rate_hz':a.fps,
       'action_semantics':f"primary applied_action is the first {cfg['dt']*1000:g}ms command; applied_action_substeps contains all commands until the next {a.fps:g}Hz observation. Use chunks and grasp_constraints.jsonl for assisted physical replay.",
       'assets':[{'source_manifest':str(run/'source_manifest.json'),'sha256':sha(run/'source_manifest.json')}],
       'dependency_packages':['genesis-world','numpy','torch']}
    if binding:metadata.update(scene_binding=binding,scene_binding_sha256=sha(run/'scene_binding.json'),pbr_verification_sha256=sha(run/'pbr_replay/verification.json'))
    writer=FrankaEpisodeWriter(run/'episodes',fps=a.fps,engine_id='genesis',engine_version=engine_version,
        scene_id=(binding['scene']['asset_id']+'@v'+str(binding['scene']['version'])) if binding else 'curobo_cloth_v1/'+cfg['task_id'],control_source='scripted_curobo_physics',
        operator_command_names=['target_'+str(i) for i in range(9)],camera_names=camera_names,
        run_metadata=metadata,seed=cfg['seed'],generation_method='scripted',worker_id='gpu-5090-cloth-v1')
    writer.start(cfg['task_id'])
    import av
    from PIL import Image
    containers={};streams={}
    for name in camera_names:
        c=av.open(str(out/(name+'.mp4')),'w');s=c.add_stream('libx264',rate=a.fps);s.width,s.height=cfg['camera_resolution'];s.pix_fmt='yuv420p';s.options={'crf':'20'}
        containers[name]=c;streams[name]=s
    for row in mapping:
        i=row['sample'];snapshot={k:data[k][i] for k in ['tick','qpos','link_poses','cloth_vertices']}
        if not binding:cams.sync(snapshot)
        images={};extras={'physics_tick':np.asarray([row['tick']],np.int64)}
        for name in camera_names:
            if binding:
                rgb=np.asarray(Image.open(run/'pbr_replay'/pv['frame_map'][row['frame']]['image_path']).convert('RGB'));transform=np.asarray(calibration[name]['camera_to_world'])
            else:
                cam=cams.scene.cameras[name];rgb=scene.array(cam.render(force_render=True)[0]).astype('uint8');transform=scene.array(cam.transform)
            images[name]=rgb
            extras[name+'_camera_to_world']=transform
            for packet in streams[name].encode(av.VideoFrame.from_ndarray(rgb,format='rgb24')):containers[name].mux(packet)
            if row['frame'] in {0,len(mapping)//2,len(mapping)-1}:Image.fromarray(rgb).save(out/(name+'_'+str(row['frame']).zfill(5)+'.png'))
        window=[commands[t] for t in range(row['tick']+1,row['tick']+round(1/(cfg['dt']*a.fps))+1)]
        extras['applied_action_substeps']=np.asarray([x['servo_commands'][0]['motor_target_qpos'] for x in window],np.float32)
        extras['requested_action_substeps']=np.asarray([x['requested_qpos'][0] for x in window],np.float32)
        extras['substep_state_after']=np.asarray([x['state_after_step'][0]['joints']+x['state_after_step'][0]['fingers']+x['state_after_step'][0]['joint_velocity'] for x in window],np.float32)
        command=commands[row['tick']+1];requested=np.asarray(command['requested_qpos'][0]);applied=np.asarray(command['servo_commands'][0]['motor_target_qpos'])
        writer.add_frame(images=images,state=np.r_[data['qpos'][i,0],data['qvel'][i,0]],action=applied,
            operator_command=requested,sim_time=row['simulation_time_s'],requested_action=requested,safe_action=applied,applied_action=applied,
            capture_timestamp_ns=round(row['simulation_time_s']*1e9),control_sequence=row['tick'],
            cloth_particles=data['cloth_vertices'][i],cloth_particle_velocities=data['cloth_velocity_fd'][i],extra_arrays=extras)
        if row['frame']%50==0:print('RENDER_PROGRESS',row['frame'],len(mapping),flush=True)
    videos={}
    for name,c in containers.items():
        for packet in streams[name].encode():c.mux(packet)
        c.close();path=out/(name+'.mp4')
        with av.open(str(path)) as video:n=sum(1 for _ in video.decode(video=0))
        if n!=len(mapping):raise RuntimeError('Decoded video frame count mismatch')
        videos[name]={'frames':n,'sha256':sha(path),'size_bytes':path.stat().st_size}
    # No human operator labelled these samples.
    from robot_data_contracts.episode import EvaluatorResultV1
    episode=writer._writer.finish(operator_success=None,evaluator=EvaluatorResultV1(evaluator_id='cloth_recorded_state',evaluator_version=evaluation['version'],
        available=evaluation['available'],success=evaluation['success'] if evaluation['available'] else None,
        metrics=evaluation['metrics'],unavailable_reason=evaluation.get('unavailable_reason')),
        failure_reason=None if evaluation['success'] else ','.join(evaluation['failed_gates']))
    # Explicitly identify reconstructed image timestamps instead of falsely using host monotonic time.
    manifest_path=episode/'manifest.json';manifest=json.loads(manifest_path.read_text())
    manifest.setdefault('scene',{}).setdefault('parameters',{})['image_capture_mode']='state_replay_no_physics_step'
    manifest['timestamp_domains']['capture_timestamp_ns']='simulation clock nanoseconds for exact recorded state; reconstructed during visual replay'
    manifest_path.write_text(json.dumps(manifest,indent=2))
    inspection=inspect_episode(manifest_path,engine_id='genesis')
    report={'videos':videos,'frame_map':mapping,'calibration':calibration,'trajectory_sha256':sha(run/'trajectory.npz'),
        'episode_path':str(episode),'episode_sha256':{str(p.relative_to(episode)):sha(p) for p in sorted(episode.rglob('*')) if p.is_file()},
        'native_episode_valid':True,'replica_fk_verified':True,'display_physics_steps':0,
        'exact_frame_ticks':True,'renderer_sha256':sha(__file__),'review_status':'SELF_REVIEWED_PROVISIONAL'}
    if binding:report.update(scene=binding['scene'],scene_binding_sha256=sha(run/'scene_binding.json'),original_scene_loaded=True,pbr_verification_sha256=sha(run/'pbr_replay/verification.json'))
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    print('REPLAY_COMPLETE',json.dumps({'videos':videos,'episode':str(episode)}),flush=True)
if __name__=='__main__':main()
