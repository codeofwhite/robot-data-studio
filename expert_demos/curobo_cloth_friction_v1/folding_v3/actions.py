"""Privileged-state task controller; every movement is planned and physically executed."""
import json
import numpy as np
from scipy.spatial.transform import Rotation
from folding_v3.metrics import measure, fold_satisfactory

# Keep the commanded closed position off the lower joint stop. At a zero
# target, contact unloading during release drove a finger 0.31 mm below its
# limit in the A-table trial. The measured joint-limit guard stays unchanged.
CLOSED_FINGER_POSITION_M = .001

def opening_target(previous,measured,goal,lead,rate,dt):
    """Advance only near measured position; never retract under inward load."""
    return np.maximum(previous,np.minimum(np.minimum(previous+rate*dt,measured+lead),goal))

def acquisition_patch_diameter(ids,vertices,spec):
    """Check the actual material patch before any approach or attachment."""
    if not ids or len(ids)>spec['max_assisted_nodes']:
        raise ValueError('Task does not permit this many assisted nodes')
    if (any(not isinstance(i,(int,np.integer)) for i in ids) or len(set(ids))!=len(ids)
            or min(ids)<0 or max(ids)>=len(vertices)):
        raise ValueError('Grasp patch must contain distinct valid material indices')
    points=np.asarray(vertices)[ids]
    diameter=float(np.linalg.norm(points[:,None]-points[None,:],axis=2).max())
    if not np.isfinite(points).all() or diameter>.04:
        raise ValueError('Grasp patch exceeds the 4 cm local diameter')
    return diameter

class Controller:
    def __init__(self,robot,rec,planner):
        from runner import motion,tick_hold
        from l_table_task import move_to
        self.robot=robot;self.rec=rec;self.planner=planner;self.scene=robot.scene;self.cfg=robot.cfg
        self.motion=motion;self.hold=tick_hold;self.move_to=move_to
        # In the A-table fold, the lower layer slid during the final descent,
        # before opening. Test a higher release to reduce that interaction.
        self.place_height=self.cfg['table_height']+(.045 if self.cfg['task_id']=='folded_transfer' else .022)
        self.rotation=Rotation.from_euler('z',90,degrees=True)*Rotation.from_euler('x',180,degrees=True)
        self.results=dict(task=self.cfg['task_id'],mode='scripted_curobo_friction_only',stages=[])
        self.mark('task_start')

    def tcp(self):return np.asarray(self.robot.state()[0]['position'])
    def move(self,p,rotation=None):
        desired=rotation or self.rotation
        current=Rotation.from_quat(np.asarray(self.robot.state()[0]['quaternion_wxyz'])[[1,2,3,0]])
        if np.linalg.norm(np.asarray(p)-self.tcp())<.0003 and (desired*current.inv()).magnitude()<.002:return
        self.move_to(self.robot,self.rec,self.planner,np.asarray(p),desired)
    def mark(self,name,**extra):
        quality=measure(self.scene.cloth_vertices(),self.scene.topology,self.cfg)
        self.rec.mark(name,**quality,**extra)
        self.results['stages'].append(dict(name=name,tick=self.scene.tick,**quality,**extra))
        (self.rec.out/'task_progress.json').write_text(json.dumps(self.results,indent=2))
    def retreat(self):
        p=self.tcp();self.move([p[0],p[1],max(.94,p[2])])
    def acquire(self,index=None,paired=None,kind='single_layer',*,patch_indices=None):
        from contact_grasp import acquire
        ids=list(patch_indices) if patch_indices is not None else ([int(index)] if paired is None else [int(index),int(paired)])
        return acquire(self,ids,kind=kind)
    def release(self):
        from contact_grasp import release
        return release(self)

    def place(self,target):
        self.move([*target,self.place_height]);self.release()
    def pull(self,index,target,clearance=.06):
        self.acquire(index);self.rec.phase='corner_adjust'
        p=self.tcp();height=max(self.cfg['table_height']+clearance,p[2]+.03)
        self.move([p[0],p[1],height]);self.move([*target,height]);self.place(target)
        self.mark('corner_adjusted',vertex_index=int(index),target_xy=list(map(float,target)))
    def fold_pair(self,moving,stationary,stage):
        self.acquire(moving);self.rec.phase='fold'
        p=self.tcp();target=self.scene.cloth_vertices()[stationary,:2].copy()
        middle=(p[:2]+target)/2
        self.move([p[0],p[1],self.cfg['table_height']+.07])
        self.move([*middle,self.cfg['table_height']+.19])
        self.move([*target,self.cfg['table_height']+.075]);self.place(target)
        self.mark('corner_adjusted',vertex_index=int(moving),paired_vertex=int(stationary),target_xy=target.tolist())
        self.mark(stage)
    def align_pair(self,moving,stationary):
        self.acquire(moving);self.rec.phase='corner_adjust'
        p=self.tcp();height=max(self.cfg['table_height']+.035,p[2]+.03)
        self.move([p[0],p[1],height])
        target=self.scene.cloth_vertices()[stationary,:2].copy()
        self.move([*target,height])
        # The lower layer is free to slide. Use its current corner again before
        # placing, rather than the position it had before the whole approach.
        target=self.scene.cloth_vertices()[stationary,:2].copy()
        self.place(target)
        self.mark('corner_adjusted',vertex_index=int(moving),paired_vertex=int(stationary),target_xy=target.tolist())
    def fold(self):
        nx,ny=self.scene.topology['physical_grid'];pairs=[(nx-1,0),(nx*ny-1,(ny-1)*nx)]
        for (moving,stationary),stage in zip(pairs,['first_corner_folded','second_corner_folded']):
            m=measure(self.scene.cloth_vertices(),self.scene.topology,self.cfg)
            v=self.scene.cloth_vertices()
            if m['layer_overlap_iou']>=.5 and np.linalg.norm(v[moving,:2]-v[stationary,:2])<=.12:
                self.align_pair(moving,stationary);self.mark(stage)
            else:self.fold_pair(moving,stationary,stage)
        for _ in range(2):
            m=measure(self.scene.cloth_vertices(),self.scene.topology,self.cfg)
            v=self.scene.cloth_vertices()
            pinch_ready=self.cfg['task_id']!='folded_transfer' or min(np.linalg.norm(v[a]-v[b]) for a,b in pairs)<=.035
            if fold_satisfactory(m) and pinch_ready:break
            moving,stationary=max(pairs,key=lambda p:np.linalg.norm(v[p[0],:2]-v[p[1],:2]))
            self.align_pair(moving,stationary)
        self.mark('fold_complete')
    def finish(self):
        self.rec.phase='release';self.retreat();self.hold(self.robot,self.rec,.5)
        self.mark('task_complete');self.rec.phase='terminal_hold';self.mark('terminal_hold');self.hold(self.robot,self.rec,1.2)
        self.results['completed']=True;(self.rec.out/'task_progress.json').write_text(json.dumps(self.results,indent=2))
