"""Measured Panda states, per-arm checks and bounded Cartesian increments."""
import math
import numpy as np
from scipy.spatial.transform import Rotation
from scene import array
from safety import Rejected,Halted,validate_action,check_measured,check_cloth,check_contact_configuration
from table_geometry import segment_hits_table
NAMES=["arm"]
def rotation(q):return Rotation.from_quat(np.array(q)[[1,2,3,0]])
def wxyz(rot):return rot.as_quat()[[3,0,1,2]]
def smooth(u):return u*u*(3-2*u)
class Robot:
    def __init__(self,scene):
        self.scene=scene;self.cfg=scene.cfg;self.arms=scene.robots;self.halted=None
        self.names=self.cfg.get('robot_names',['arm'])
        if len(self.names)!=len(self.arms):raise ValueError('Robot names and articulated entities differ')
        check_contact_configuration(scene.contact_configuration())
        self.refs=[array(r.init_qpos) for r in self.arms]
        self.targets=[array(r.get_qpos()) for r in self.arms]
        self.limits=[np.stack([array(x) for x in r.get_dofs_limit()],axis=-1).reshape(9,2) for r in self.arms]
        self.peaks={"finger_limit_m":0.,"arm_limit_rad":0.,"tcp_speed_m_s":0.,"finger_speed_m_s":0.}
        for r in self.arms:
            r.set_dofs_kp(np.array(self.cfg["kp"]));r.set_dofs_kv(np.array(self.cfg["kv"]))
            caps=np.r_[self.cfg["arm_force_limits"],self.cfg["finger_force_limit"],self.cfg["finger_force_limit"]]
            r.set_dofs_force_range(-caps,caps)
        self.gravity_masses=[array(r.get_links_inertial_mass()) for r in self.arms]
        self.previous=self.state()
    def state(self):
        result=[]
        for r in self.arms:
            hand=r.get_link("hand");q=array(hand.get_quat());p=array(hand.get_pos())+rotation(q).apply(self.cfg["tcp_offset"])
            pos=array(r.get_qpos())
            result.append({"position":p.tolist(),"quaternion_wxyz":q.tolist(),"joints":pos[:7].tolist(),"fingers":pos[7:].tolist(),
                           "joint_velocity":array(r.get_dofs_velocity()).tolist(),
                           "actuator_effort":array(r.get_dofs_control_force()).tolist(),
                           "effort_note":"Actuator command effort; not calibrated contact force"})
        return result
    def tick(self,targets=None,record=None,check_workspace=True):
        if self.halted:raise Halted(self.halted)
        if targets is not None:
            if len(targets)!=len(self.arms) or any(np.asarray(q).shape!=(9,) or not np.isfinite(q).all() for q in targets):
                raise ValueError('Every configured arm requires one finite 9-joint target')
            self.targets=[np.array(q).copy() for q in targets]
        commands=[];command_trace=[]
        for i,(r,q,ref,limits) in enumerate(zip(self.arms,self.targets,self.refs,self.limits)):
            torque=np.zeros(r.n_dofs)
            for link,mass in zip(r.links,self.gravity_masses[i]):
                if mass<=0:continue
                J=array(r.get_jacobian(link,local_point=np.array(link.inertial_pos)))
                torque-=J[:3].T@np.array([0.,0.,-9.81*float(mass)])
            if not np.isfinite(torque).all() or (abs(torque[:7])>self.cfg["arm_force_limits"]).any():
                self.halted="Gravity compensation is nonfinite or exceeds motor limits";raise Halted(self.halted)
            command=q.copy();command[:7]+=torque[:7]/np.array(self.cfg["kp"])[:7]
            if (command[:7]<limits[:7,0]).any() or (command[:7]>limits[:7,1]).any():
                self.halted="Gravity-compensated motor target exceeds joint limits";raise Halted(self.halted)
            commands.append(command-ref)
            command_trace.append({"gravity_torque_nm":torque[:7].tolist(),"motor_target_qpos":command.tolist()})
        self.last_servo_command=command_trace
        # Native torque caps remain active on every servo step.
        for r,command in zip(self.arms,commands):r.control_dofs_position(command)
        self.scene.world.step();self.scene.tick+=1
        state=self.state()
        try:
            for i,(r,item,last,lim) in enumerate(zip(self.arms,state,self.previous,self.limits)):
                q=np.r_[item["joints"],item["fingers"]];vel=np.array(item["joint_velocity"]);eff=np.array(item["actuator_effort"])
                excess=np.maximum(lim[:,0]-q,np.maximum(q-lim[:,1],0))
                fd=(q-np.r_[last["joints"],last["fingers"]])/self.cfg["dt"]
                tcp=np.array(item["position"]);speed=np.linalg.norm(tcp-last["position"])/self.cfg["dt"]
                self.peaks["finger_limit_m"]=max(self.peaks["finger_limit_m"],float(excess[7:].max()))
                self.peaks["arm_limit_rad"]=max(self.peaks["arm_limit_rad"],float(excess[:7].max()))
                self.peaks["tcp_speed_m_s"]=max(self.peaks["tcp_speed_m_s"],float(speed))
                self.peaks["finger_speed_m_s"]=max(self.peaks["finger_speed_m_s"],float(max(abs(vel[7:]).max(),abs(fd[7:]).max())))
                check_measured(q,vel,eff,lim,self.cfg,self.names[i])
                check_measured(q,fd,eff,lim,self.cfg,self.names[i]+" finite difference")
                if not np.allclose(vel,fd,atol=2e-5,rtol=0):raise Halted("IPC position/velocity mismatch")
                if speed>self.cfg["max_tcp_speed"]:raise Halted(self.names[i]+": measured TCP speed exceeded")
                if check_workspace and ((tcp<self.cfg["workspace_low"]).any() or (tcp>self.cfg["workspace_high"]).any()):raise Halted(self.names[i]+": measured TCP outside workspace")
                if segment_hits_table(last["position"],tcp,self.cfg):raise Halted(self.names[i]+": measured TCP crossed table slab")
            check_contact_configuration(self.scene.contact_configuration())
            check_cloth(self.scene.physics_health(),self.cfg)
            self.check_contacts()
        except Halted as e:
            self.halted=str(e);raise
        finally:
            self.previous=state
            if record:record(self.scene,state)
        return state
    def check_contacts(self):
        # Native contacts are an additional check only; IPC contact coverage is checked separately.
        for r in self.arms:
            contacts=r.get_contacts()
            if not contacts:continue
            a=array(contacts["link_a"]);b=array(contacts["link_b"])
            valid=array(contacts.get("valid_mask",np.ones(a.shape,dtype=bool))).astype(bool)
            mine={l.idx:l.name for l in r.links}
            table={l.idx for l in self.scene.table.links};floor={l.idx for l in self.scene.floor.links}
            for aa,bb in zip(a[valid].reshape(-1),b[valid].reshape(-1)):
                aa=int(aa);bb=int(bb)
                if aa not in mine and bb not in mine:continue
                arm,other=(aa,bb) if aa in mine else (bb,aa)
                name=mine[arm]
                if other in table|floor and name in ["link0","base"]:continue
                raise Halted("Forbidden rigid contact: "+name+" with link "+str(other))
    def prepare(self,action):
        state=self.state();acts=validate_action(action,self.cfg,state)
        starts=[np.array(q).copy() for q in self.targets];paths=[];ends=[]
        for i,(r,st,lim) in enumerate(zip(self.arms,state,self.limits)):
            a=acts.get(self.names[i])
            if a is None:paths.append(np.repeat(starts[i][None,:],13,axis=0));ends.append(starts[i].copy());continue
            q0=np.r_[st["joints"],st["fingers"]];prev=q0.copy();path=[]
            rot0=rotation(st["quaternion_wxyz"]);pos0=np.array(st["position"])
            for k in range(13):
                u=k/12;rot=Rotation.from_rotvec(u*a["rotation"])*rot0
                q,err=r.inverse_kinematics(link=r.get_link("hand"),pos=pos0+u*a["translation"],quat=wxyz(rot),
                    local_point=self.cfg["tcp_offset"],init_qpos=prev,dofs_idx_local=np.arange(7),
                    max_samples=1,max_solver_iters=40,damping=.03,max_step_size=.1,return_error=True)
                q=array(q);err=array(err)
                if np.linalg.norm(err[:3])>self.cfg["ik_position_tolerance"] or np.linalg.norm(err[3:])>self.cfg["ik_rotation_tolerance"]:raise Rejected(self.names[i]+": IK residual too large")
                if (q[:7]<lim[:7,0]).any() or (q[:7]>lim[:7,1]).any():raise Rejected("IK joint limit")
                prev=q.copy();q[7:]=starts[i][7:]
                path.append(q)
            path=np.array(path);path[0]=starts[i];end=path[-1].copy()
            if a["gripper"]!="keep":end[7:]=.04 if a["gripper"]=="open" else 0.
            paths.append(path);ends.append(end)
        duration=max(1.,self.cfg["release_duration_s"])
        for path,a in zip(paths,[acts.get(n) for n in self.names]):
            if a is not None:
                duration=max(duration,2*np.linalg.norm(a["translation"])/(.7*self.cfg["max_tcp_speed"]),
                    2*12*np.max(abs(np.diff(path[:,:7],axis=0)))/self.cfg["max_joint_target_speed"])
        return paths,starts,ends,int(math.ceil(duration/self.cfg["dt"]))
    def execute(self,action,record=None):
        paths,starts,ends,steps=self.prepare(action)
        for k in range(1,steps+1):
            u=smooth(k/steps);slot=min(int(u*12),11);fraction=u*12-slot
            targets=[]
            for path,start,end in zip(paths,starts,ends):
                q=path[slot]*(1-fraction)+path[slot+1]*fraction
                q[7:]=start[7:]+u*(end[7:]-start[7:]);targets.append(q)
            self.tick(targets,record)
        for _ in range(40):self.tick(record=record)
        return {"physics_steps":steps+40,"state":self.state(),"peaks":self.peaks}
