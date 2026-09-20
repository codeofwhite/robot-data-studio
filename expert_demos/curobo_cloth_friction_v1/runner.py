"""Force-limited true-contact cloth execution with per-motion cuRobo replanning."""
import argparse,json,sys,os,subprocess,time,traceback,math
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from profiles import configuration,ROOT
from scene_adapter import prepare,sha,bind_scene
from record_episode import Recorder
from tabletop_v2 import TASKS as TABLETOP_TASKS
from folding_v3 import TASKS as FOLDING_TASKS
from fixtures_v4 import TASKS as FIXTURE_TASKS
BATCH_TASKS=(*TABLETOP_TASKS,*FOLDING_TASKS,*FIXTURE_TASKS)
PY='/data/zhanghejun/SIMPLE/.venv/bin/python'
def validate_scene_hover_plan(result,cfg):
    if result.get('diagnostic_only'):raise ValueError('Diagnostic plans cannot initialize an execution')
    expected={k:v['sha256'] for k,v in cfg['scene_binding']['collision_meshes'].items()}
    if result.get('success') is not True or result['metadata'].get('collision_mesh_sha256')!=expected:raise ValueError('Hover plan does not match original scene collision geometry')
    if result['metadata']['scene']!=cfg['scene_binding']['scene']:raise ValueError('Hover plan belongs to another scene version')
    inverse=Rotation.from_euler('z',cfg['yaws'][0],degrees=True).inv();origin=inverse.apply(-np.asarray(cfg['bases'][0]))
    for name in expected:
        pose=np.asarray(result['metadata']['world']['mesh'][name]['pose'])
        if np.linalg.norm(pose[:3]-origin)>1e-8 or (Rotation.from_quat(pose[[4,5,6,3]])*inverse.inv()).magnitude()>1e-8:
            raise ValueError('Hover plan belongs to a different robot base transform')
    if 'grasp_seed' not in result:raise ValueError('Original-scene hover plan must identify its grasp material vertex and orientation')

class PlannerProcess:
    def __init__(self,out,cfg):
        self.out=out;self.count=0;(out/'plans').mkdir();self.log=(out/'planner_stdout.log').open('x')
        self.err=(out/'planner_stderr.log').open('x')
        env=os.environ.copy()
        if not env.get('CUDA_VISIBLE_DEVICES'):
            raise ValueError('Set an explicit GPU mask for the friction experiment')
        self.p=subprocess.Popen([PY,'-B','-u',str(ROOT/'planner.py'),'--config',str(out/'config.json')],
              stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.err,env=env,text=True,bufsize=1)
        self.read('PLANNER_READY ')
    def read(self,prefix):
        while True:
            line=self.p.stdout.readline()
            if not line:raise RuntimeError('cuRobo worker exited; see planner_stderr.log')
            self.log.write(line);self.log.flush()
            if line.startswith(prefix):return json.loads(line[len(prefix):])
    def call(self,job):
        self.p.stdin.write(json.dumps(job)+'\n');self.p.stdin.flush();r=self.read('PLAN_RESULT ')
        if job.get('op')!='fk':
            self.count+=1;(self.out/'plans'/f'{self.count:04d}.json').write_text(json.dumps({'request':job,'result':r},indent=2))
        return r
    def close(self):
        if self.p.poll() is None:
            self.p.stdin.write('{"shutdown":true}\n');self.p.stdin.flush()
            try:self.p.wait(timeout=20)
            except subprocess.TimeoutExpired:self.p.terminate();self.p.wait(timeout=10)
        self.log.close();self.err.close()
def fk_check(planner,robot):
    state=robot.state()[0];r=planner.call({'op':'fk','q':state['joints']})['fk']
    pe=float(np.linalg.norm(np.asarray(r['tcp_world'])-state['position']))
    a=Rotation.from_quat(np.asarray(r['quaternion_wxyz'])[[1,2,3,0]])
    b=Rotation.from_quat(np.asarray(state['quaternion_wxyz'])[[1,2,3,0]])
    re=float((a*b.inv()).magnitude())
    if pe>.0002 or re>.002:raise RuntimeError(f'cuRobo/physics FK mismatch {pe} m, {re} rad')
    return {'position_error_m':pe,'rotation_error_rad':re}
def tick_hold(robot,rec,seconds):
    for _ in range(round(seconds/robot.cfg['dt'])):robot.tick(record=rec)
def motion(action,robot,rec,planner,gripper_width=None):
    from safety import validate_action,Halted
    state=robot.state()[0];validate_action({'arm':action},robot.cfg,[state])
    start=np.r_[state['joints'],state['fingers']];g=action.get('gripper','keep')
    end_fingers=np.full(2,.04 if g=='open' else 0.) if g!='keep' else robot.targets[0][7:].copy()
    if gripper_width is not None:
        if not np.isfinite(gripper_width) or not 0<=gripper_width<=.04:raise ValueError('Invalid working finger opening')
        end_fingers=np.full(2,gripper_width)
    d=np.asarray(action.get('translation',[0,0,0.]));rv=np.asarray(action.get('rotation',[0,0,0.]))
    if np.linalg.norm(d)+np.linalg.norm(rv)>0:
        fk_check(planner,robot)
        r=Rotation.from_rotvec(rv)*Rotation.from_quat(np.asarray(state['quaternion_wxyz'])[[1,2,3,0]])
        goal=np.asarray(state['position'])+d
        result=planner.call({'q':state['joints'],'tcp_world':goal.tolist(),'quaternion_wxyz':r.as_quat()[[3,0,1,2]].tolist()})
        if not result.get('success'):raise Halted('cuRobo rejected motion: '+str(result.get('status') or result.get('error')))
        q=np.asarray(result['q']);dt=robot.cfg['dt']
        if np.max(abs(q[0]-start[:7]))>.001:raise Halted('Planner start differs from measured robot')
        # Uniform time scaling preserves the planned configuration path.
        joint_length=np.max(np.sum(abs(np.diff(q,axis=0)),axis=0))
        duration=max((len(q)-1)*dt,joint_length/.12,np.linalg.norm(d)/.018,np.linalg.norm(rv)/.12,1.)
        n=math.ceil(duration/dt);old=np.linspace(0,1,len(q));new=np.linspace(0,1,n+1)
        path=np.stack([np.interp(new,old,q[:,i]) for i in range(7)],axis=1)
        for index,arm in enumerate(path[1:]):
            u=(index+1)/n;f=start[7:]+(end_fingers-start[7:])*(u*u*(3-2*u))
            robot.tick([np.r_[arm,f]],record=rec)
        tick_hold(robot,rec,.16)
        measured=np.asarray(robot.state()[0]['position']);error=float(np.linalg.norm(measured-goal))
        rec.mark('motion_complete',tracking_error_m=error,planner_id=planner.count)
        if error>.003:raise Halted('Measured endpoint tracking error exceeds 3 mm: '+str(error))
    else:
        n=round(1./robot.cfg['dt']);arm=robot.targets[0][:7].copy()
        for i in range(1,n+1):
            u=i/n;f=start[7:]+(end_fingers-start[7:])*(u*u*(3-2*u))
            robot.tick([np.r_[arm,f]],record=rec)
        tick_hold(robot,rec,.16)
def scene_grasp_goal(vertices,topology,cfg):
    """Choose a reachable hanging material boundary, using current simulated geometry."""
    v=np.asarray(vertices);nx,ny=topology['physical_grid'];boundary=np.arange(0,nx*ny,nx)
    lo=np.asarray(cfg['table']['position'])-np.asarray(cfg['table']['half_extents'])
    seed=cfg.get('scene_grasp_seed')
    if seed:
        index=int(seed['vertex_index'])
        if index not in boundary:raise ValueError('Planned source grasp is not a material boundary')
        desired=Rotation.from_quat(np.asarray(seed['quaternion_wxyz'])[[1,2,3,0]])
        offset=seed['approach_offset_m']
    else:
        candidates=boundary[(v[boundary,1]<lo[1]+.04)&(v[boundary,2]<cfg['table_height']-.06)]
        if len(candidates)==0:raise RuntimeError('No accessible hanging boundary in the actual scene; tabletop pinch controller is not verified')
        index=int(candidates[np.argmin(v[candidates,2])]);desired=Rotation.from_euler('y',90,degrees=True);offset=[-.08,0,0]
    rest=np.asarray(topology['rest_vertices'])
    neighbours=np.argsort(np.linalg.norm(rest-rest[index],axis=1))[:4]
    # Approach from the left edge. Jaw closing axis is world Y, normal to the hanging panel.
    contact_offset=seed.get('tcp_contact_offset_world_m',[0,0,0]) if seed else [0,0,0]
    return {'position':(v[index]+contact_offset).tolist(),'material_position':v[index].tolist(),
        'tcp_contact_offset_world_m':contact_offset,'quaternion_wxyz':desired.as_quat()[[3,0,1,2]].tolist(),
        'vertex_index':index,'neighbours':neighbours.tolist(),'source':'current simulated hanging boundary; privileged state scripted expert',
        'geometry_tick':None,'approach_offset_m':offset}

def approach_scene_goal(robot,rec,planner,goal):
    target=np.asarray(goal['position']);desired=Rotation.from_quat(np.asarray(goal['quaternion_wxyz'])[[1,2,3,0]])
    # First move to a clear point left of the edge, then insert the fingertips.
    for waypoint in [target+goal['approach_offset_m'],target]:
        for index in range(100):
            state=robot.state()[0];d=waypoint-np.asarray(state['position'])
            rv=(desired*Rotation.from_quat(np.asarray(state['quaternion_wxyz'])[[1,2,3,0]]).inv()).as_rotvec()
            if np.linalg.norm(d)<.0003 and np.linalg.norm(rv)<.002:break
            if np.linalg.norm(d)>.018:d*=.018/np.linalg.norm(d)
            if np.linalg.norm(rv)>robot.cfg['max_rotation_rad']:rv*=robot.cfg['max_rotation_rad']/np.linalg.norm(rv)
            motion({'translation':d.tolist(),'rotation':rv.tolist()},robot,rec,planner)
        else:raise RuntimeError('Original-scene approach did not converge')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--task',choices=['corner_lift','smooth','hold','l_table_transfer_flatten',*BATCH_TASKS],default='corner_lift')
    p.add_argument('--material',default='medium');p.add_argument('--initial',default='nominal');p.add_argument('--seed',type=int,default=194731)
    p.add_argument('--negative-no-close',action='store_true');p.add_argument('--pregrasp-start',action='store_true')
    scene_args=p.add_mutually_exclusive_group(required=True)
    scene_args.add_argument('--scene');scene_args.add_argument('--legacy-scene',action='store_true',help='Explicitly reproduce the historical simplified diagnostic world')
    p.add_argument('--active-robot',default='FrankaLeft');p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--scene-hover-plan')
    p.add_argument('--grasp-probe-only',action='store_true')
    p.add_argument('--foundation',help='Verified matched-control foundation required for full tasks')
    p.add_argument('--probe-vertex',type=int)
    p.add_argument('--physics-dt',type=float,choices=[.004,.002,.01],default=.004)
    p.add_argument('--gripper-friction',type=float,default=.6)
    p.add_argument('--table-friction',type=float,default=.6)
    p.add_argument('--physics-device',type=int,choices=[0,1],default=0)
    p.add_argument('--visual-demo-profile',action='store_true',
        help='L-table numerical comparison: 100 Hz integration and regularized low-speed friction; measured gates unchanged')
    a=p.parse_args()
    if not a.grasp_probe_only and not a.prepare_only:
        if not a.foundation:p.error('Full friction tasks require --foundation')
        from contact_grasp import verify_foundation
        verify_foundation(a.foundation)
    if a.visual_demo_profile and a.task not in ('l_table_transfer_flatten',*BATCH_TASKS):p.error('Visual numerical profile is restricted to the L-table task')
    if a.scene and a.pregrasp_start:p.error('Historical simplified-scene pregrasp initialization cannot be used in an original scene')
    if a.scene and a.initial!='nominal':p.error('Original scene layout must not be labelled as a legacy shifted-cloth variant')
    if a.scene and a.task=='smooth':p.error('The historical smooth action sequence is not a validated original-scene controller')
    # cuRobo resolves relative mesh paths against its installed asset directory.
    # Bind every runtime artifact to this absolute run root before generating paths.
    out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
    cfg=configuration(a.material,a.initial,a.seed);cfg['task_id']=a.task;cfg['negative_control']=a.negative_no_close
    cfg['physics_device']=a.physics_device
    if a.visual_demo_profile:
        cfg['dt']=.01;cfg['record_stride']=2
        cfg['ipc']['contact_eps_velocity']=.005
        cfg['numerical_profile']={'name':'visual_demo_100hz','physics_dt_s':.01,
            'contact_regularization_velocity_m_s':.005,'snapshot_interval_s':.02,
            'limitation':'Numerical simulation profile, not a calibrated real-material model; measured motion and contact gates unchanged.'}
    if a.scene:
        bind_scene(out,cfg,a.scene,a.active_robot)
        cfg['preparation']['max_settle_s']=30.
        cfg['robot_initialization']={'mode':'authored_source_scene_pose'}
        if a.scene_hover_plan:
            result=json.loads(Path(a.scene_hover_plan).read_text())
            validate_scene_hover_plan(result,cfg)
            cfg['home']=result['q'][-1]+[.04,.04]
            cfg['scene_grasp_seed']=result['grasp_seed']
            cfg['preparation']['readiness_scope']='selected material grasp neighbourhood; hanging tail may remain in motion'
            cfg['robot_initialization']={'mode':'independent_scene_hover_initialization','plan_sha256':sha(a.scene_hover_plan),
                'note':'Initial pose derived from a cuRobo plan in this scene; transit from authored pose is NOT claimed as physically executed.'}
            shutil_path=out/'initialization_plan.json';shutil_path.write_bytes(Path(a.scene_hover_plan).read_bytes())
    if a.pregrasp_start:
        source=ROOT.parents[1]/'data/expert_demos/curobo-cloth-v1/preflight_safe_hover/result.json'
        result=json.loads(source.read_text())
        if result['success'] is not True:raise ValueError('Safe-hover initialization plan failed')
        initial=result['q'][-1]
        cfg['grasp_goal']=json.loads((source.parent/'grasp_goal.json').read_text())
        cfg['approach_finger_position_m']=.035
        cfg['home']=initial+[.04,.04]
        cfg['robot_initialization']={'mode':'independent_safe_hover_initialization','source_q_sha256':sha(source),
           'note':'New physical simulation from generated folded cloth and the specified initial arm configuration. No state continuation, attachments, or cloth reset during rollout.'}
    elif not a.scene:cfg['robot_initialization']={'mode':'high_home_full_approach'}
    if a.task=='l_table_transfer_flatten':
        if not a.scene or cfg.get('task_spec',{}).get('id')!='l_table_transfer_flatten':p.error('L-table task requires its registered L-table scene')

        cfg['approach_finger_position_m']=.035
        cfg['assisted_grasp']={'enabled':True,'strength_rate':100.*(cfg['dt']/.004)**2,
            'strength_reference_dt_s':.004,'strength_rule':'100 * (dt / 0.004)^2; verified by hanging-state target-error comparison',
            'mode':'local_soft_position_constraint',
            'authorization':'User explicitly allowed assisted holding for the complete demonstration',
            'limitation':'Kinematic pinch assistance; not evidence of friction-only grasp or hardware success'}
        cfg['preparation']['max_settle_s']=6.
        # Solve the inner linear system accurately enough for strict Newton convergence.
        # Keep the original stopping precision and measured motion/contact checks.
        cfg['ipc'].update(newton_tolerance=.005,newton_translation_tolerance=.005,
                          linear_system_tolerance=1e-6)
        cfg['solver_precision']={'profile':'accurate_inner_linear_solve',
            'reason':'The default inner linear tolerance caused repeated outer Newton iterations during articulated motion.',
            'validation':'100-step diagnostic with initial link poses verified against the recorded state; full-task validation remains required'}
    if a.task in BATCH_TASKS:
        if not a.scene or cfg.get('task_spec',{}).get('id')!=a.task:p.error('Tabletop task requires its matching registered scene')

        mask=os.environ.get('CUDA_VISIBLE_DEVICES','')
        if not mask or a.physics_device>=len(mask.split(',')):p.error('Use an explicit valid GPU mask')
        cfg['approach_finger_position_m']=.035
        cfg['assisted_grasp']={'enabled':True,'strength_rate':cfg['task_spec']['assistance_strength'],
            'mode':'local_soft_position_constraint','authorization':'User approved '+cfg['task_spec']['batch_id']+' with local gripper assistance',
            'limitation':'Assisted simulation, not friction-only gripping or hardware evidence'}
        cfg['preparation']['max_settle_s']=.5
        cfg['ipc'].update(newton_tolerance=.005,newton_translation_tolerance=.005,linear_system_tolerance=1e-6)
        cfg['numerical_baseline']='007: 100 Hz integration, local assistance strength 100, accurate inner linear solve'
    # Apply the friction profile after source-scene binding; old task metadata
    # remains preserved in scene_source, but cannot authorize an attachment.
    if not 0<=a.gripper_friction<=1 or not 0<=a.table_friction<=1:
        p.error('Synthetic friction probe coefficients must be in [0, 1]')
    cfg['dt']=a.physics_dt;cfg['record_stride']=round(.02/a.physics_dt)
    cfg['surface_friction']={'table':a.table_friction,'gripper':a.gripper_friction}
    cfg['ipc'].update(contact_eps_velocity=.0001,linear_system_tolerance=1e-6)
    cfg['assisted_grasp']={'enabled':False,'mode':'disabled'}
    cfg['grasp_probe_only']=a.grasp_probe_only;cfg['probe_vertex']=a.probe_vertex
    if a.foundation:cfg['foundation']={'path':str(Path(a.foundation).resolve()),'sha256':sha(a.foundation)}
    cfg['contact_grasp']={
        'mode':'friction_only','minimum_lift_m':.008,'probe_lift_m':.015,
        'hold_s':.6,'maximum_material_slip_m':.004,'maximum_pad_distance_m':.0015,
        'minimum_loaded_gap_m':.0002,'maximum_loaded_gap_m':.02,
        'closed_finger_target_m':0.,'support_clearance_m':.010,
        'geometry_note':'Inner faces of the unchanged MJCF finger pad boxes; geometric proximity is not contact force.'}
    cfg['numerical_profile']={'name':'friction_only_v1','physics_dt_s':cfg['dt'],
        'contact_regularization_velocity_m_s':cfg['ipc']['contact_eps_velocity'],
        'measured_material':False}
    cfg['numerical_baseline']='No cloth constraints; 250 Hz baseline, 500 Hz convergence probe; unchanged force and safety limits'
    if 'task_spec' in cfg:
        cfg['task_spec'].update(grasp_mode='friction_only',grasp_assistance_authorized=False)
    if a.negative_no_close and not a.grasp_probe_only:
        p.error('No-close control requires --grasp-probe-only so it completes the same lift/release sequence')
    (out/'config.json').write_text(json.dumps(cfg,indent=2))
    scene_module=prepare(out,cfg);planner=None;rec=None;robot=None;error=None;started=time.time()
    if a.prepare_only:
        print('SCENE_PREPARED',json.dumps({'scene':cfg.get('scene_binding',{}).get('scene'),'output':str(out)}));return
    tabletop_execute=None
    if a.task in BATCH_TASKS:
        # Initialization may take minutes. Resolve late task/helper imports
        # from this run's immutable source snapshot before initialization, so
        # concurrent work on another task cannot change an in-flight run.
        import importlib
        batch_name=cfg['task_spec']['batch_id'];batch_module=importlib.import_module(batch_name)
        frozen=out/'source_snapshot'
        sys.path.insert(0,str(frozen))
        batch_module.__path__=[str(frozen/batch_name)]
        tabletop_execute=importlib.import_module(batch_name+'.'+a.task).execute
        (out/'task_code_binding.json').write_text(json.dumps({
            'source_root':str(frozen),'task_module':tabletop_execute.__module__,
            'task_module_path':str(Path(sys.modules[tabletop_execute.__module__].__file__).resolve()),
            'policy':'Task and late helper imports resolve from the per-run source snapshot'},indent=2))
    try:
        if a.scene and cfg['scene_binding']['initial_cloth_edge_ratio']>cfg['gates']['edge_ratio']:
            raise RuntimeError('Original authored cloth exceeds the existing strain gate; needs physically settled initial geometry, not a relaxed success threshold')
        import genesis as gs
        gs.init(backend=gs.cpu,precision='32',seed=cfg['seed'],logging_level='warning')
        import torch
        torch.cuda.set_device(a.physics_device)
        scene=scene_module.Scene(cfg)
        if a.task in FOLDING_TASKS and 'garment' in scene.topology:
            scene.initial_geometry_audit.update(rest_shape=scene.topology['rest_shape'],flat_rest_preserved=False,
                reference_geometry_preserved=True,current_shape=scene.topology['garment']['initial_embedding'])
        from robot import Robot
        robot=Robot(scene);rec=Recorder(out,scene,robot)
        (out/'contact_audit.json').write_text(json.dumps(scene.contact_configuration(),indent=2))
        (out/'initial_geometry_audit.json').write_text(json.dumps(scene.initial_geometry_audit,indent=2))
        previous=scene.cloth_vertices().copy();stable=0;ready_ids=None
        if a.scene and cfg.get('scene_grasp_seed'):
            rest=np.asarray(scene.topology['rest_vertices']);index=cfg['scene_grasp_seed']['vertex_index']
            ready_ids=np.argsort(np.linalg.norm(rest-rest[index],axis=1))[:4]
        for i in range(math.ceil(cfg['preparation'].get('max_settle_s',8.)/.5)):
            tick_hold(robot,rec,.5);v=scene.cloth_vertices().copy();displacements=np.linalg.norm(v-previous,axis=1);diff=float(displacements.max());previous=v
            ready_diff=float(displacements[ready_ids].max()) if ready_ids is not None else diff
            stable=stable+1 if ready_diff<=cfg['preparation']['settled_motion_tolerance_m'] else 0
            rec.events.append({'name':'settle_observation','tick':scene.tick,'max_displacement_last_half_second_m':diff,'readiness_displacement_m':ready_diff,
                'readiness_vertex_ids':ready_ids.tolist() if ready_ids is not None else 'all','consecutive_stable_intervals':stable})
            print('SETTLE_OBSERVATION',scene.tick,diff,ready_diff,stable,flush=True)
            if i>=5 and stable>=2:break
        if stable<2 and a.task not in ('l_table_transfer_flatten',*BATCH_TASKS):raise RuntimeError('Cloth settling failed')
        if a.pregrasp_start and float(scene.cloth_vertices()[:,2].max()-cfg['table_height'])>.006:
            raise RuntimeError('Initial cloth is held above its settled folded state; possible initial robot interference')
        rec.mark('grasp_patch_stable' if ready_ids is not None else 'settled',max_displacement_last_half_second_m=diff,
            readiness_displacement_m=ready_diff,whole_cloth_settled=diff<=cfg['preparation']['settled_motion_tolerance_m'])
        planner=PlannerProcess(out,cfg)
        (out/'fk_audit.json').write_text(json.dumps(fk_check(planner,robot),indent=2))
        if a.grasp_probe_only:
            from contact_grasp import run_probe
            run_probe(robot,rec,planner);return
        if a.task=='hold':tick_hold(robot,rec,1.);rec.mark('terminal_hold');return
        if a.task=='l_table_transfer_flatten':
            from l_table_task import execute
            execute(robot,rec,planner);return
        if a.task in BATCH_TASKS:
            tabletop_execute(robot,rec,planner);return
        actions=json.loads((ROOT/'reference_actions.json').read_text())['actions'];rec.phase='approach'
        variant=cfg['initial_variant'];offset=variant['offset_xy'];yaw=variant['yaw_deg']
        rz=Rotation.from_euler('z',yaw,degrees=True)
        def transformed(action):
            b=dict(action)
            if 'translation' in b:b['translation']=rz.apply(b['translation']).tolist()
            return b
        scene_goal=None
        if a.scene:
            scene_goal=scene_grasp_goal(scene.cloth_vertices(),scene.topology,cfg);scene_goal['geometry_tick']=scene.tick
            (out/'grasp_goal.json').write_text(json.dumps(scene_goal,indent=2))
            approach_scene_goal(robot,rec,planner,scene_goal)
        elif a.pregrasp_start:
            # Leave 5 mm of joint-limit headroom during contact approach.
            # The original hard limits, effort caps, and measured checks remain unchanged.
            motion({'gripper':'keep'},robot,rec,planner,gripper_width=cfg['approach_finger_position_m'])
            target=np.asarray(cfg['grasp_goal']['position']).copy()
            target[:2]=np.asarray(cfg['square']['center_xy'])+rz.apply(np.r_[target[:2]-[-.12,-.08],0])[:2]
            desired=rz*Rotation.from_quat(np.asarray(cfg['grasp_goal']['quaternion_wxyz'])[[1,2,3,0]])
            for index in range(20):
                state=robot.state()[0];delta=target-state['position']
                rotation=(desired*Rotation.from_quat(np.asarray(state['quaternion_wxyz'])[[1,2,3,0]]).inv()).as_rotvec()
                if np.linalg.norm(delta)<.0003 and np.linalg.norm(rotation)<.002:break
                if np.linalg.norm(delta)>.015:delta*=.015/np.linalg.norm(delta)
                if np.linalg.norm(rotation)>cfg['max_rotation_rad']:rotation*=cfg['max_rotation_rad']/np.linalg.norm(rotation)
                print('APPROACH',index+1,flush=True)
                motion({'translation':delta.tolist(),'rotation':rotation.tolist()},robot,rec,planner)
            else:raise RuntimeError('Approach did not converge')
        else:
            if np.linalg.norm(offset)>0:motion({'translation':offset+[0.]},robot,rec,planner)
            if yaw:motion({'rotation':[0,0,float(np.deg2rad(yaw))]},robot,rec,planner)
            for i,action in enumerate(actions[:10]):
                print('ACTION',i+1,flush=True);motion(transformed(action),robot,rec,planner)
        v=scene.cloth_vertices();tcp=np.asarray(robot.state()[0]['position'])
        index=int(np.argmin(np.linalg.norm(v-tcp,axis=1)))
        rest=np.asarray(scene.topology['rest_vertices']);neighbours=np.flatnonzero(np.linalg.norm(rest-rest[index],axis=1)<.035).tolist()
        if scene_goal is not None:index=scene_goal['vertex_index'];neighbours=scene_goal['neighbours']
        rec.phase='grasp';rec.mark('before_close',vertex_index=index,neighbours=neighbours)
        motion({'gripper':'keep' if a.negative_no_close else 'close'},robot,rec,planner);rec.mark('after_close')
        clearance=cfg.get('scene_grasp_seed',{}).get('post_close_translation_m')
        if clearance is not None:
            rec.phase='edge_clearance';motion({'translation':clearance},robot,rec,planner);rec.mark('edge_clearance_complete')
        rec.phase='lift';motion({'translation':[0,0,.015]},robot,rec,planner)
        tick_hold(robot,rec,.5);rec.mark('held')
        if a.task=='smooth':
            rec.phase='unfold'
            for i,action in enumerate(actions[12:29],13):print('ACTION',i,flush=True);motion(transformed(action),robot,rec,planner)
        rec.phase='release';rec.mark('before_release');motion({'gripper':'open'},robot,rec,planner);rec.mark('after_release')
        rec.phase='terminal_hold';tick_hold(robot,rec,1.);rec.mark('terminal_hold')
    except BaseException:
        error=traceback.format_exc();(out/'failure.txt').write_text(error);print(error,flush=True)
    finally:
        if rec:rec.close()
        if robot and robot.scene.assisted_trace is not None:robot.scene.assisted_trace.close()
        if planner:planner.close()
        report={'task':a.task,'material':a.material,'initial':a.initial,'seed':a.seed,'negative_control':a.negative_no_close,
          'halted':error,'physics_ticks':rec.scene.tick if rec else 0,'elapsed_wall_s':time.time()-started,
          'planner':'cuRobo MotionGen','actual_physics':'Genesis FEM Cloth + IPC + full articulated Franka',
          'runtime_cloth_setters':0,'attached_cloth':bool(robot and robot.scene.assisted_grasp_used),
          'grasp_assistance':cfg.get('assisted_grasp',{'enabled':False}),'review_status':'SELF_REVIEWED_PROVISIONAL'}
        if a.scene:report.update(scene=cfg['scene_binding']['scene'],active_robot=cfg['scene_binding']['active_robot'],
            passive_robots=cfg['scene_binding']['passive_robots'],control_scope=cfg['scene_binding']['control_scope'])
        (out/'run_summary.json').write_text(json.dumps(report,indent=2))
        print('RUN_FINISHED',json.dumps({k:v for k,v in report.items() if k!='halted'}),flush=True)
    if error:sys.exit(2)
def run_reference_matrix():
    """Run each reference task; stop extra variants after a task's first failure."""
    import concurrent.futures,threading
    from contact_grasp import verify_foundation
    p=argparse.ArgumentParser()
    p.add_argument('--run-reference-matrix',required=True)
    p.add_argument('--foundation',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--gpus',required=True)
    a=p.parse_args();verify_foundation(a.foundation)
    output=Path(a.output).resolve();output.mkdir(parents=True,exist_ok=False)
    references=json.loads(Path(a.run_reference_matrix).read_text())
    groups={}
    for item in references:groups.setdefault(item['task'],[]).append(item)
    devices=a.gpus.split(',')
    if len(set(devices))!=len(devices) or not all(x.isdigit() for x in devices):
        raise ValueError('Use distinct explicit GPU indices')
    priority=['unfold_corner','directed_flatten','edge_retrieve_spread','translate_rotate_align','towel_half_fold','unfold_half','garment_flip','place_in_basket','retrieve_from_basket','hang_on_rod','retrieve_from_rod','cover_box','l_table_transfer_flatten']
    queue=sorted(groups.items(),key=lambda row:priority.index(row[0]));lock=threading.Lock();results=[]
    def save():
        report={'foundation':str(Path(a.foundation).resolve()),'gpus':devices,
            'reference_count':len(references),'task_count':len(groups),'results':results,
            'review_status':'SELF_REVIEWED_PROVISIONAL',
            'policy':'Run first variant of every task; a task failure blocks its further variants, not other task types. Successful physics still requires video review.'}
        temporary=output/'report.tmp.json';temporary.write_text(json.dumps(report,indent=2))
        temporary.replace(output/'report.json')
    def worker(gpu):
        while True:
            with lock:
                if not queue:return
                task,items=queue.pop(0)
            failed=False
            for item in items:
                variant=item['variant'] or 'reference'
                if failed:
                    with lock:
                        results.append(dict(task=task,variant=variant,status='not_run_after_task_failure',reference=item));save()
                    continue
                run=output/task/variant/'run_001';run.parent.mkdir(parents=True,exist_ok=True)
                source=Path(item['source_run']);config=json.loads((source/'config.json').read_text())
                if sha(source/'config.json')!=item['source_config_sha256']:
                    raise ValueError('Assisted reference configuration changed: '+str(source))
                argv=[sys.executable,'-B',str(ROOT/'launch.py'),'runner.py',
                    '--scene',item['scene'],'--task',task,'--physics-dt','0.004',
                    '--seed',str(item['seed']),'--foundation',str(Path(a.foundation).resolve()),'--output',str(run)]
                if (source/'initialization_plan.json').exists():
                    argv+=['--scene-hover-plan',str(source/'initialization_plan.json')]
                env=dict(os.environ,CLOTH_GPU=gpu)
                print('FULL_TASK_START',task,variant,'gpu',gpu,flush=True)
                with (run.parent/'launch.log').open('x') as log:
                    process=subprocess.run(argv,env=env,stdout=log,stderr=subprocess.STDOUT)
                if (run/'run_summary.json').exists():
                    with (run.parent/'evaluation.log').open('x') as log:
                        evaluation_process=subprocess.run([sys.executable,'-B',str(ROOT/'evaluate.py'),str(run)],stdout=log,stderr=subprocess.STDOUT)
                    if evaluation_process.returncode:raise RuntimeError('Evaluation failed: '+str(run))
                    evaluation=json.loads((run/'evaluation.json').read_text())
                    success=evaluation['success'] is True
                    row=dict(task=task,variant=variant,run=str(run),gpu=gpu,
                        status='physics_passed_video_pending' if success else 'failed',
                        failed_gates=evaluation['failed_gates'],returncode=process.returncode,reference=item)
                else:
                    success=False;row=dict(task=task,variant=variant,run=str(run),gpu=gpu,
                        status='failed_before_summary',returncode=process.returncode,reference=item)
                (run.parent/'launch.json').write_text(json.dumps({'argv':argv,'CLOTH_GPU':gpu,'returncode':process.returncode},indent=2))
                failed=not success
                with lock:results.append(row);save()
                print('FULL_TASK_END',task,variant,row['status'],row.get('failed_gates'),flush=True)
    with lock:save()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(devices)) as executor:
        futures=[executor.submit(worker,gpu) for gpu in devices]
        for future in futures:future.result()
    print('MATRIX_COMPLETE',str(output/'report.json'),flush=True)

if __name__=='__main__':
    if '--run-reference-matrix' in sys.argv:run_reference_matrix()
    else:main()
