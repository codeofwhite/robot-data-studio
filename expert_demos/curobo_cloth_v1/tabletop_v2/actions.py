"""Shared single-corner actions, with re-observation at each acquisition stage."""
import json
import numpy as np
from scipy.spatial.transform import Rotation
from tabletop_v2.metrics import measure, satisfactory


class Controller:
    def __init__(self,robot,rec,planner):
        from runner import motion,tick_hold
        from l_table_task import move_to
        self.robot=robot;self.rec=rec;self.planner=planner;self.scene=robot.scene;self.cfg=robot.cfg
        self.motion=motion;self.hold=tick_hold;self.move_to=move_to
        self.rotation=Rotation.from_euler('z',90,degrees=True)*Rotation.from_euler('x',180,degrees=True)
        self.scene.assisted_trace=(rec.out/'grasp_constraints.jsonl').open('x')
        self.results=dict(task=self.cfg['task_id'],mode='scripted_curobo_assisted_grasp',stages=[])
        self.mark('task_start')

    def move(self,p):
        self.move_to(self.robot,self.rec,self.planner,np.asarray(p),self.rotation)

    def tcp(self):return np.asarray(self.robot.state()[0]['position'])

    def mark(self,name,**extra):
        m=measure(self.scene.cloth_vertices(),self.scene.topology,self.cfg)
        self.rec.mark(name,**m,**extra)
        self.results['stages'].append(dict(name=name,tick=self.scene.tick,**m,**extra))
        (self.rec.out/'task_progress.json').write_text(json.dumps(self.results,indent=2))

    def retreat(self):
        p=self.tcp();self.move([p[0],p[1],max(.98,p[2]+.08)])

    def acquire(self,index):
        from safety import Halted
        self.rec.phase='acquire'
        for attempt in range(3):
            self.retreat()
            self.motion({'gripper':'open'},self.robot,self.rec,self.planner,gripper_width=.035)
            point=self.scene.cloth_vertices()[index].copy()
            hover=point.copy();hover[2]=max(self.cfg['table_height']+.11,point[2]+.09)
            self.move(hover)
            # The cloth can move during the hover trajectory; choose a fresh
            # target after reaching hover, rather than reusing the stale point.
            point=self.scene.cloth_vertices()[index].copy()
            goal=point.copy();goal[2]=max(point[2]+.005,self.cfg['table_height']+.018)
            self.rec.mark('grasp_reobserved',vertex_index=int(index),attempt=attempt+1,goal=goal.tolist())
            self.move(goal)
            self.rec.mark('before_close',vertex_index=int(index))
            self.motion({'gripper':'close'},self.robot,self.rec,self.planner)
            distance=float(np.linalg.norm(self.scene.cloth_vertices()[index]-self.tcp()))
            if distance<=.032:
                attachment=self.scene.attach_cloth_patch([index])
                self.rec.mark('assisted_grasp_attached',**attachment)
                self.hold(self.robot,self.rec,.7)
                self.mark('acquired',vertex_index=int(index))
                return
            self.rec.mark('grasp_reacquisition_required',vertex_index=int(index),distance_m=distance,attempt=attempt+1,
                          reason='Selected material point moved during descent/closing; reopen and reobserve')
            self.motion({'gripper':'open'},self.robot,self.rec,self.planner,gripper_width=.035)
        raise Halted('Selected corner stayed outside the local acquisition region after three recorded approaches')

    def release(self):
        self.scene.release_cloth_patch();self.rec.mark('assisted_grasp_released')
        self.motion({'gripper':'open'},self.robot,self.rec,self.planner,gripper_width=.035)
        self.hold(self.robot,self.rec,.6)

    def pull(self,index,target,clearance=.055):
        self.acquire(index);self.rec.phase='pull'
        p=self.tcp();height=max(self.cfg['table_height']+clearance,p[2]+.035)
        self.move([p[0],p[1],height]);self.move([target[0],target[1],height])
        self.move([target[0],target[1],self.cfg['table_height']+.021]);self.release()
        self.mark('corner_adjusted',vertex_index=int(index),target_xy=list(target))

    def spread(self,max_pulls=4,min_pulls=1,probe_after_pulls=None):
        targets={int(k):np.array(v) for k,v in self.cfg['task_spec']['target_corners_xy_m'].items()}
        corrected=set()
        for count in range(max_pulls):
            quality=measure(self.scene.cloth_vertices(),self.scene.topology,self.cfg)
            if count>=min_pulls and satisfactory(quality,self.cfg['task_id']):break
            if len(corrected)==len(targets):corrected.clear()
            vertices=self.scene.cloth_vertices()
            candidates=sorted((i for i in targets if i not in corrected),key=lambda i:np.linalg.norm(vertices[i,:2]-targets[i]),reverse=True)
            index=candidates[0]
            if probe_after_pulls is not None and count>=probe_after_pulls:
                from safety import Halted
                index=None
                for candidate in candidates:
                    point=vertices[candidate].copy()
                    point[2]=max(self.cfg['table_height']+.11,point[2]+.09)
                    result=self.planner.call({'q':self.robot.state()[0]['joints'],'tcp_world':point.tolist(),
                                             'quaternion_wxyz':self.rotation.as_quat()[[3,0,1,2]].tolist()})
                    self.rec.mark('corner_approach_probe',vertex_index=int(candidate),goal=point.tolist(),
                                  planner_id=self.planner.count,success=bool(result.get('success')),status=result.get('status'),
                                  reason='Cloth moved after earlier pulls; select a currently reachable remaining corner')
                    if result.get('success'):
                        index=candidate;break
                if index is None:raise Halted('No remaining corner has a collision-checked cuRobo approach')
            self.pull(index,targets[index]);corrected.add(index)

    def finish(self):
        self.rec.phase='release';self.retreat();self.hold(self.robot,self.rec,1.)
        self.mark('task_complete');self.rec.phase='terminal_hold';self.rec.mark('terminal_hold')
