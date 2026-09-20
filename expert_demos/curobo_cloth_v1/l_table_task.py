"""Privileged-state cuRobo expert with explicitly recorded local pinch assistance."""
import json,math
import numpy as np
from scipy.spatial.transform import Rotation

def task_metrics(vertices,topology,cfg):
    from scipy.spatial import ConvexHull
    v=np.asarray(vertices);area=float(topology['flat_area_m2']);lo,hi=np.asarray(cfg['task_spec']['target_region_xy_m'])
    inside=((v[:,:2]>=lo)&(v[:,:2]<=hi)).all(axis=1)
    projected=float(ConvexHull(v[:,:2]).volume) if len(v)>2 and np.linalg.matrix_rank(v[:,:2]-v[:,:2].mean(0))==2 else 0.
    heights=v[:,2]-cfg['table_height']
    supported=inside&(heights>=-.001)&(heights<=.03)
    return {'target_vertex_fraction':float(inside.mean()),'target_surface_vertex_fraction':float(supported.mean()),'projected_area_fraction':projected/area,
        'height_p95_m':float(np.percentile(heights,95)),'height_max_m':float(heights.max()),
        'cloth_center_world_m':v.mean(0).tolist()}

def move_to(robot,rec,planner,position,rotation):
    """One full collision-checked path, conservatively retimed from FK and joints."""
    from runner import tick_hold,fk_check
    from safety import Halted
    state=robot.state()[0];position=np.asarray(position,float)
    if ((position<robot.cfg['workspace_low'])|(position>robot.cfg['workspace_high'])).any():raise Halted('Task waypoint outside workspace')
    fk_check(planner,robot)
    result=planner.call({'q':state['joints'],'tcp_world':position.tolist(),'quaternion_wxyz':rotation.as_quat()[[3,0,1,2]].tolist()})
    if not result.get('success'):raise Halted('cuRobo rejected task waypoint: '+str(result.get('status') or result.get('error')))
    q=np.asarray(result['q']);dt=robot.cfg['dt']
    if np.max(abs(q[0]-state['joints']))>.001:raise Halted('Task planner start mismatch')
    # Sample FK over the planned curve, not just endpoint displacement. Runtime
    # measured speed, contact, force and strain checks remain active every tick.
    ids=np.arange(len(q))
    tcp=np.asarray([planner.call({'op':'fk','q':q[i].tolist()})['fk']['tcp_world'] for i in ids])
    # Limit each segment directly rather than slowing the entire path to its
    # worst segment. A 0.35 s start/stop ramp keeps the same path and speed caps.
    durations=np.maximum(np.max(abs(np.diff(q,axis=0)),axis=1)/.18,
                         np.linalg.norm(np.diff(tcp,axis=0),axis=1)/.035)
    clock=np.r_[0.,np.cumsum(np.maximum(durations,1e-6))]
    base=max(float(clock[-1]),1.);clock*=base/clock[-1];ramp=.35
    steps=math.ceil((base+ramp)/dt);times=np.linspace(0,base+ramp,steps+1)
    progress=np.where(times<ramp,times**2/(2*ramp),np.where(times>base,base-(base+ramp-times)**2/(2*ramp),times-ramp/2))
    path=np.stack([np.interp(progress,clock,q[:,i]) for i in range(7)],axis=1)
    fingers=robot.targets[0][7:].copy()
    rec.mark('planned_waypoint',planner_id=planner.count,goal=position.tolist(),duration_s=steps*dt)
    print('TASK_WAYPOINT',rec.phase,position.tolist(),steps*dt,flush=True)
    for arm in path[1:]:robot.tick([np.r_[arm,fingers]],record=rec)
    tick_hold(robot,rec,.2)
    error=float(np.linalg.norm(np.asarray(robot.state()[0]['position'])-position))
    rec.mark('motion_complete',planner_id=planner.count,tracking_error_m=error)
    if error>.003:raise Halted('Task endpoint error exceeds 3 mm: '+str(error))

def execute(robot,rec,planner):
    from runner import motion,tick_hold
    scene=robot.scene;cfg=robot.cfg
    scene.assisted_trace=(rec.out/'grasp_constraints.jsonl').open('x')
    orientation=Rotation.from_euler('z',90,degrees=True)*Rotation.from_euler('x',180,degrees=True)
    nx,ny=scene.topology['physical_grid'];corners=[0,nx-1,(ny-1)*nx,nx*ny-1]
    targets={corners[0]:[.51,-.35],corners[1]:[.51,.05],corners[2]:[.21,-.35],corners[3]:[.21,.05]}
    results={'mode':'scripted_curobo_assisted_grasp','initial':task_metrics(scene.cloth_vertices(),scene.topology,cfg),'stages':[]}
    def mark(name):
        metrics=task_metrics(scene.cloth_vertices(),scene.topology,cfg);results['stages'].append({'name':name,'tick':scene.tick,**metrics})
        rec.mark(name,**metrics);(rec.out/'task_progress.json').write_text(json.dumps(results,indent=2))
    def move(p):move_to(robot,rec,planner,p,orientation)
    def acquire(index,first=False):
        rec.phase='acquire' if first else 'regrasp_flatten'
        point=scene.cloth_vertices()[index].copy();goal=point.copy();goal[2]=max(goal[2]+.005,cfg['table_height']+.018)
        if first:
            (rec.out/'grasp_goal.json').write_text(json.dumps({'position':goal.tolist(),'material_position':point.tolist(),
                'vertex_index':int(index),'quaternion_wxyz':orientation.as_quat()[[3,0,1,2]].tolist(),
                'source':'observed FEM material corner; assisted pinch'},indent=2))
        hover=goal+[0,0,.12 if first else .075]
        if np.linalg.norm(np.asarray(robot.state()[0]['position'])-hover)>.003:move(hover)
        # Leave travel margin during regrasp contact instead of commanding the
        # fingers against their upper joint stops throughout the approach.
        opening=None if first else cfg['approach_finger_position_m']
        motion({'gripper':'open'},robot,rec,planner,gripper_width=opening);move(goal)
        rec.mark('before_close',vertex_index=int(index));motion({'gripper':'close'},robot,rec,planner)
        # One corner node prevents artificial stiffening of the cloth. Its anchor
        # offset is captured from the measured hand/cloth at attachment time.
        attachment=scene.attach_cloth_patch([index]);rec.mark('assisted_grasp_attached',**attachment)
        tick_hold(robot,rec,.7)
    def release():
        scene.release_cloth_patch();rec.mark('assisted_grasp_released')
        motion({'gripper':'open'},robot,rec,planner);tick_hold(robot,rec,.6)
    acquire(corners[1],True);mark('acquired')
    rec.phase='drag';p=np.asarray(robot.state()[0]['position']);move(p+[0,-.07,0]);mark('drag_complete')
    rec.phase='hang';p=np.asarray(robot.state()[0]['position']);move([p[0],p[1],1.32]);move([.02,.02,1.32]);tick_hold(robot,rec,.8);mark('hanging_complete')
    rec.phase='transfer';move([.27,-.32,1.32]);mark('transfer_complete')
    rec.phase='lay_down';move([.27,-.32,.94]);move([.42,-.12,.86]);move([.51,.05,.803]);release();mark('lay_down_complete')
    # Re-observe each material corner, lift it clear, draw it towards its target,
    # and let the unsupported cloth settle. No second pinned corner is used.
    corrected=set()
    for _ in range(4):
        quality=task_metrics(scene.cloth_vertices(),scene.topology,cfg)
        if corrected and quality['target_surface_vertex_fraction']>=.95 and quality['projected_area_fraction']>=.88 and quality['height_p95_m']<=.012:break
        vertices=scene.cloth_vertices()
        index=max((i for i in corners if i not in corrected),key=lambda i:np.linalg.norm(vertices[i,:2]-targets[i]))
        p=np.asarray(robot.state()[0]['position']);move([p[0],p[1],max(.96,p[2]+.05)])
        acquire(index);p=np.asarray(robot.state()[0]['position']);height=max(.835,p[2]+.035);move([p[0],p[1],height])
        xy=targets[index];move([xy[0],xy[1],height]);move([xy[0],xy[1],.801]);release();mark('corner_spread_'+str(index));corrected.add(index)
    rec.phase='release';p=np.asarray(robot.state()[0]['position']);move(p+[0,0,.16]);tick_hold(robot,rec,1.)
    results['final']=task_metrics(scene.cloth_vertices(),scene.topology,cfg);results['completed']=True
    mark('task_complete');rec.phase='terminal_hold';rec.mark('terminal_hold')
