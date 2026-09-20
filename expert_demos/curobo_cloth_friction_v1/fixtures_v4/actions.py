"""Shared single-corner actions, with re-observation at each acquisition stage."""
import json
import numpy as np
from scipy.spatial.transform import Rotation
from fixtures_v4.metrics import measure, satisfactory


def grasp_position(point,cfg):
    """Retain the table pinch clearance at the actual local supporting surface."""
    x,y,z=map(float,point);floor=float(cfg['table_height']);f=cfg['task_spec']['fixture']
    cx,cy=f['center_xy']
    if f['kind']=='box':
        w,d,h=f['size_m'];top=f['base_height_m']+h
        if abs(x-cx)<=w/2 and abs(y-cy)<=d/2 and z>=top-.006:floor=top
    elif f['kind']=='basket':
        w,d,_=f['size_m'];wall=f['wall_m']
        if abs(x-cx)<w/2-wall and abs(y-cy)<d/2-wall:floor=f['base_height_m']+wall
    return [x,y,max(z+.005,floor+.018)]


class Controller:
    def __init__(self,robot,rec,planner):
        from runner import motion,tick_hold
        from l_table_task import move_to
        self.robot=robot;self.rec=rec;self.planner=planner;self.scene=robot.scene;self.cfg=robot.cfg
        self.motion=motion;self.hold=tick_hold;self.move_to=move_to
        self.rotation=Rotation.from_euler('z',90,degrees=True)*Rotation.from_euler('x',180,degrees=True)
        self.results=dict(task=self.cfg['task_id'],mode='scripted_curobo_friction_only',stages=[])
        self.mark('task_start')

    def fixture_top(self):
        f=self.cfg['task_spec']['fixture']
        return f['center_height_m']+f['radius_m'] if f['kind']=='rod' else f['base_height_m']+f['size_m'][2]

    def move(self,p):
        self.move_to(self.robot,self.rec,self.planner,np.asarray(p),self.rotation)

    def tcp(self):return np.asarray(self.robot.state()[0]['position'])

    def approach_height(self,point):
        # Once material is on the receiving table, the distant rod/basket does
        # not set every vertical approach height. cuRobo still checks the full
        # original obstacle geometry for each resulting trajectory.
        f=self.cfg['task_spec']['fixture'];x,y=f['center_xy']
        half=(f['length_m']/2,f['radius_m']) if f['kind']=='rod' else np.asarray(f['size_m'][:2])/2
        near=abs(point[0]-x)<=half[0]+.20 and abs(point[1]-y)<=half[1]+.20
        return max(self.cfg['table_height']+.12,self.fixture_top()+.10 if near else 0.)

    def mark(self,name,**extra):
        m=measure(self.scene.cloth_vertices(),self.scene.topology,self.cfg)
        self.rec.mark(name,**m,**extra)
        self.results['stages'].append(dict(name=name,tick=self.scene.tick,**m,**extra))
        (self.rec.out/'task_progress.json').write_text(json.dumps(self.results,indent=2))

    def retreat(self):
        p=self.tcp();self.move([p[0],p[1],max(self.approach_height(p),p[2]+.08)])

    def acquire(self,index):
        from contact_grasp import acquire
        return acquire(self,[int(index)])
    def release(self):
        from contact_grasp import release
        return release(self)

    def pull(self,index,target,clearance=.023):
        self.acquire(index);self.rec.phase='pull'
        # The previous 35 mm lift carried much of a folded strip with the hand.
        # A 3 mm lift preserves table support while drawing out the selected hem.
        p=self.tcp();height=max(self.cfg['table_height']+clearance,p[2]+.003)
        self.move([p[0],p[1],height]);self.move([target[0],target[1],height])
        self.move([target[0],target[1],self.cfg['table_height']+.021]);self.release()
        self.mark('corner_adjusted',vertex_index=int(index),target_xy=list(target))

    def select_reachable(self,candidates,check_grasp=True):
        from safety import Halted
        for candidate in candidates:
            point=self.scene.cloth_vertices()[candidate].copy()
            heights=[max(self.approach_height(point),point[2]+.09)]
            if check_grasp:heights.append(grasp_position(point,self.cfg)[2])
            valid=True
            for height in heights:
                goal=[float(point[0]),float(point[1]),float(height)]
                result=self.planner.call({'q':self.robot.state()[0]['joints'],'tcp_world':goal,
                    'quaternion_wxyz':self.rotation.as_quat()[[3,0,1,2]].tolist()})
                self.rec.mark('corner_approach_probe',vertex_index=int(candidate),goal=goal,
                    planner_id=self.planner.count,success=bool(result.get('success')),status=result.get('status'),
                    reason='Unexecuted candidate reachability probe in current fixture geometry')
                if not result.get('success'):valid=False;break
            if valid:return candidate
        raise Halted('No reachable acquisition candidate; all probes retained')

    def spread_targets(self):
        from safety import Halted
        spec=self.cfg['task_spec'];nominal={int(k):np.asarray(v) for k,v in spec['target_corners_xy_m'].items()}
        lo,hi=np.asarray(spec['target_region_xy_m']);q=self.robot.state()[0]['joints']
        # Variant 3's outer corner (.54,-.515) is outside the retained wrist's
        # low workspace. A 2 cm / 1.5 cm inward translation fits the same table.
        # Test the full rectangle before grasping, retaining every probe.
        for delta in ([0.,0.],[-.02,.015]):
            targets={i:p+delta for i,p in nominal.items()};valid=True;probes=[]
            if any(np.any(p<lo) or np.any(p>hi) for p in targets.values()):continue
            for index,xy in targets.items():
                for offset in [.021,.023,.12]:
                    goal=[*map(float,xy),self.cfg['table_height']+offset]
                    result=self.planner.call({'q':q,'tcp_world':goal,'quaternion_wxyz':self.rotation.as_quat()[[3,0,1,2]].tolist()})
                    probes.append(dict(vertex_index=index,goal=goal,planner_id=self.planner.count,
                                       success=bool(result.get('success')),status=result.get('status')))
                    if not result.get('success'):valid=False;break
                if not valid:break
            self.rec.mark('spread_target_probes',translation_xy_m=delta,probes=probes,all_reachable=valid)
            if valid:
                self.rec.mark('spread_target_selection',translation_xy_m=delta,
                              nominal_targets={str(i):p.tolist() for i,p in nominal.items()},
                              executed_targets={str(i):p.tolist() for i,p in targets.items()},
                              reason='Reachable unfolding rectangle within receiving-table region; this retrieval task has no center-alignment requirement')
                return targets
        raise Halted('No reachable unfolding rectangle within the receiving-table region; all probes retained')

    def spread(self,max_pulls=6,min_pulls=2):
        targets=self.spread_targets();corrected=set()
        for count in range(max_pulls):
            if count>=min_pulls and satisfactory(measure(self.scene.cloth_vertices(),self.scene.topology,self.cfg),self.cfg['task_id']):break
            v=self.scene.cloth_vertices();candidates=sorted((i for i in targets if i not in corrected),key=lambda i:np.linalg.norm(v[i,:2]-targets[i]),reverse=True)
            if not candidates:
                # Later pulls can displace earlier corners. Reobserve them for
                # a bounded second pass instead of declaring four tugs complete.
                corrected.clear();candidates=sorted(targets,key=lambda i:np.linalg.norm(v[i,:2]-targets[i]),reverse=True)
            index=self.select_reachable(candidates);self.pull(index,targets[index]);corrected.add(index)

    def lift_clear(self,height=1.29):
        p=self.tcp();self.rec.phase='lift';self.move([p[0],p[1],height])

    def lay_on_table(self,index):
        spec=self.cfg['task_spec'];xy=np.asarray(spec['target_center_world_m'][:2]);rest=np.asarray(self.scene.topology['rest_vertices'])
        offset=rest[index,:2]-rest[:,:2].mean(0)
        # Target material axes: long u follows world +Y, v follows world -X.
        world_offset=np.array([-offset[1],offset[0]]);target=xy+world_offset;opposite=xy-world_offset
        self.rec.phase='table_transfer';self.move([*xy,1.27]);self.move([*opposite,.96])
        # Reuse the descending sweep from the validated original L-table demo:
        # deposit the trailing material before drawing the held edge across it.
        self.rec.phase='lay_sweep';self.mark('lay_sweep_started')
        self.move([*xy,.86]);self.move([*target,.804]);self.release()
        self.mark('transferred_to_table');self.spread();self.mark('spread_complete')

    def finish(self):
        self.rec.phase='release';self.retreat();self.hold(self.robot,self.rec,3.)
        self.mark('task_complete');self.rec.phase='terminal_hold';self.rec.mark('terminal_hold')
