"""Physics recorder. Post-step observations and pre-step commands are explicitly distinguished."""
import json,hashlib
from pathlib import Path
import numpy as np
class Recorder:
    def __init__(self,out,scene,robot):
        self.out=Path(out);self.scene=scene;self.robot=robot;self.phase='settle'
        self.log=(self.out/'physics.jsonl').open('x');self.rows=[];self.events=[]
        self.previous=scene.cloth_vertices().copy();self.previous_tick=scene.tick
        self.capture()
    def capture(self):
        s=self.scene;snap=s.snapshot()
        v=s.cloth_vertices();delta=s.tick-self.previous_tick
        velocity=(v-self.previous)/(delta*s.cfg['dt']) if delta else np.zeros_like(v)
        snap['cloth_velocity_fd']=velocity;snap['qvel']=[x['joint_velocity'] for x in self.robot.state()]
        if not self.rows or int(self.rows[-1]['tick'])!=s.tick:self.rows.append({k:np.asarray(v) for k,v in snap.items()})
        self.previous=v.copy();self.previous_tick=s.tick
    def __call__(self,s,state):
        row={'tick':s.tick,'simulation_time_s':s.tick*s.cfg['dt'],'phase':self.phase,
             'state_after_step':state,'command_applied_from_tick':s.tick-1,
             'servo_commands':self.robot.last_servo_command,'requested_qpos':[q.tolist() for q in self.robot.targets],
             'cloth_health':s.physics_health()}
        self.log.write(json.dumps(row,allow_nan=False)+'\n');self.log.flush()
        if s.tick%s.cfg['record_stride']==0:self.capture()
        if s.tick%250==0:print('PHYSICS_PROGRESS',s.tick,self.phase,flush=True)
    def mark(self,name,**values):
        self.capture();self.events.append({'name':name,'tick':self.scene.tick,**values});self.save()
    def save(self):
        self.capture()
        np.savez_compressed(self.out/'trajectory.npz',**{k:np.asarray([r[k] for r in self.rows]) for k in self.rows[0]})
        (self.out/'events.json').write_text(json.dumps(self.events,indent=2))
        (self.out/'recording_schema.json').write_text(json.dumps({'physics_dt_s':self.scene.cfg['dt'],'snapshot_stride':self.scene.cfg['record_stride'],
            'trajectory_state':'Measured state AFTER the tick number of integration steps.',
            'action_alignment':'physics.jsonl row tick=t+1 contains command applied to trajectory observation at tick=t.',
            'cloth_velocity':'Finite difference of actual recorded cloth positions across snapshot interval.',
            'runtime_cloth_setters':0,'initialization_setters':1},indent=2))
    def close(self):
        self.save();self.log.close()
