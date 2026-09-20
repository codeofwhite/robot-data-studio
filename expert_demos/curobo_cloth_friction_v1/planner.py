"""Isolated cuRobo worker. All requests/results are JSON; physics runs in another environment."""
import argparse,json,traceback,hashlib
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
class Planner:
    def __init__(self,cfg):
        import torch
        from curobo.types.base import TensorDeviceType
        from curobo.wrap.reacher.motion_gen import MotionGen,MotionGenConfig
        from curobo.util_file import load_yaml,join_path,get_robot_configs_path
        from curobo.geom.sdf.world import CollisionCheckerType
        self.cfg=cfg;self.ta=TensorDeviceType();self.base=np.asarray(cfg['bases'][0])
        self.rot=Rotation.from_euler('z',cfg['yaws'][0],degrees=True)
        rc=load_yaml(join_path(get_robot_configs_path(),'franka.yml'))['robot_cfg']
        # SIMPLE's installed fork no longer adds collision branches automatically.
        # Explicitly retain all original collision links, including both fingers.
        rc['kinematics']['link_names']=list(rc['kinematics']['collision_link_names'])
        from collision_model import calibrated_robot_config
        rc=calibrated_robot_config(rc,load_yaml,Path(get_robot_configs_path()))
        table=np.asarray(cfg['table']['position'])
        center=self.rot.inv().apply(table-self.base);quat=self.rot.inv().as_quat()[[3,0,1,2]]
        world={'cuboid':{'table':{'dims':(2*np.asarray(cfg['table']['half_extents'])).tolist(),'pose':np.r_[center,quat].tolist()}}}
        binding=cfg.get('scene_binding')
        if binding:
            from scene_adapter import verify_scene_sources
            verify_scene_sources(binding)
            origin=self.rot.inv().apply(-self.base)
            world={'mesh':{}}
            for name,mesh in binding['collision_meshes'].items():
                if digest(mesh['path'])!=mesh['sha256']:raise ValueError('Scene collision mesh changed: '+name)
                world['mesh'][name]={'file_path':mesh['path'],'pose':np.r_[origin,quat].tolist()}
        self.world=world
        self.mg=MotionGen(MotionGenConfig.load_from_robot_config(rc,world,self.ta,
             interpolation_dt=cfg['dt'],num_ik_seeds=32,num_trajopt_seeds=4,
             position_threshold=.001,rotation_threshold=.01,use_cuda_graph=False,
             self_collision_check=True,self_collision_opt=True,
             collision_activation_distance=.002,
             collision_checker_type=CollisionCheckerType.MESH if binding else CollisionCheckerType.PRIMITIVE))
        self.meta={'planner':'cuRobo MotionGen','world':world,'self_collision_check':True,
          'finger_collision_model':'open finger configuration; actual MJCF pads conservatively covered by cell-bounding spheres; closed-finger motion checked by full physics',
          'collision_adapter_sha256':digest(Path(__file__).parent/'collision_model.py'),'cloth_obstacle':False,
          'cloth_handling':'deformable state is evaluated by Genesis IPC, not cuRobo',
          'robot_config_sha256':digest(join_path(get_robot_configs_path(),'franka.yml'))}
        if binding:self.meta.update(scene=binding['scene'],source_sha256=binding['source_sha256'],
            collision_mesh_sha256={k:v['sha256'] for k,v in binding['collision_meshes'].items()},passive_robots=binding['passive_robots'])
    def joint(self,q):
        from curobo.types.state import JointState
        return JointState.from_position(self.ta.to_device([q]),joint_names=self.mg.joint_names)
    def fk(self,q):
        state=self.mg.compute_kinematics(self.joint(q))
        p=state.ee_pose.position.detach().cpu().numpy().reshape(3)
        w=state.ee_pose.quaternion.detach().cpu().numpy().reshape(4)
        r=self.rot*Rotation.from_quat(w[[1,2,3,0]])
        hand=self.base+self.rot.apply(p);tcp=hand+r.apply(self.cfg['tcp_offset'])
        return {'hand_world':hand.tolist(),'tcp_world':tcp.tolist(),'quaternion_wxyz':r.as_quat()[[3,0,1,2]].tolist()}
    def plan(self,job):
        from curobo.types.math import Pose
        from curobo.wrap.reacher.motion_gen import MotionGenPlanConfig
        q=job['q'];r=Rotation.from_quat(np.asarray(job['quaternion_wxyz'])[[1,2,3,0]])
        tcp=np.asarray(job['tcp_world']);hand=tcp-r.apply(self.cfg['tcp_offset'])
        p=self.rot.inv().apply(hand-self.base);quat=(self.rot.inv()*r).as_quat()[[3,0,1,2]]
        goal=Pose(position=self.ta.to_device([p.tolist()]),quaternion=self.ta.to_device([quat.tolist()]))
        result=self.mg.plan_single(self.joint(q),goal,MotionGenPlanConfig(max_attempts=4,enable_graph=True))
        ok=bool(result.success.item());out={'success':ok,'status':str(result.status),'start_fk':self.fk(q),'metadata':self.meta}
        if ok:
            path=result.get_interpolated_plan();a=path.position.detach().cpu().numpy()
            out.update(q=a.tolist(),dt=self.cfg['dt'],goal_fk=self.fk(a[-1].tolist()),
                       planner_time_s=float(result.total_time))
            if not np.isfinite(a).all():raise ValueError('Nonfinite planned path')
        return out
def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--preflight');p.add_argument('--request');a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text());planner=Planner(cfg)
    if a.preflight:
        fk=planner.fk(cfg['home'][:7]);target=np.asarray(fk['tcp_world'])+[0,0,.01]
        result=planner.plan(json.loads(Path(a.request).read_text()) if a.request else {'q':cfg['home'][:7],'tcp_world':target.tolist(),'quaternion_wxyz':fk['quaternion_wxyz']})
        Path(a.preflight).write_text(json.dumps(result,indent=2));print('PREFLIGHT_RESULT',json.dumps({k:v for k,v in result.items() if k!='q'}),flush=True)
        raise SystemExit(0 if result['success'] else 2)
    print('PLANNER_READY '+json.dumps(planner.meta),flush=True)
    import sys
    for line in sys.stdin:
        job=json.loads(line)
        if job.get('shutdown'):break
        try:r={'fk':planner.fk(job['q'])} if job.get('op')=='fk' else planner.plan(job)
        except Exception:r={'success':False,'error':traceback.format_exc()}
        print('PLAN_RESULT '+json.dumps(r),flush=True)
if __name__=='__main__':main()
