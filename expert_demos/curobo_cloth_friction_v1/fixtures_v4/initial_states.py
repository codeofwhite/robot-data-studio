"""Authored isometric starts, or independently initialized recorded parent ends."""
import hashlib,json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

PARENTS={'retrieve_from_rod':'hang_on_rod','retrieve_from_basket':'place_in_basket'}

def grid():
    return np.array([[u,v,0.] for v in np.linspace(-.15,.15,61) for u in np.linspace(-.2,.2,81)])

def transform(points,center,yaw=90,height=.784):
    return Rotation.from_euler('z',yaw,degrees=True).apply(points)+[*center,height]

def parent_run(batch,task,variant):
    if task not in PARENTS:return None
    root=Path(batch)/'tasks'/PARENTS[task]/variant/'runs'
    for run in reversed(sorted(root.glob('*'))):
        report=run/'evaluation.json'
        if report.exists() and json.loads(report.read_text()).get('success'):return run
    raise ValueError('Run successful parent first: '+PARENTS[task]+'/'+variant)

def initial_points(task,cfg,parent=None):
    if task in PARENTS:
        if parent is None:raise ValueError('Retrieval task requires a recorded physical parent state')
        topology=json.loads((parent/'physical_scene/assets/cloth_topology.json').read_text())
        with np.load(parent/'trajectory.npz') as a:physical=a['cloth_vertices'][-1]
        indices=np.asarray(topology['visual_indices']);weights=np.asarray(topology['visual_weights'])
        return np.sum(physical[indices]*weights[:,:,None],axis=1)
    profiles={'flat':[0]*20,'mild':[0]*6+[45]*2+[-45]*2+[0]*10,'reverse':[0]*8+[-45]*2+[45]*2+[0]*8}
    angles=np.repeat(np.deg2rad(profiles[cfg['initial_profile']]),4)
    u=np.r_[0,np.cumsum(.005*np.cos(angles))];z=np.r_[0,np.cumsum(.005*np.sin(angles))]
    u-=(u.max()+u.min())/2;z-=z.min()
    local=np.array([[x,v,h] for v in np.linspace(-.15,.15,61) for x,h in zip(u,z)])
    return transform(local,cfg['initial_center'])

def lineage(parent):
    if parent is None:return {'kind':'authored_isometric_initial_state'}
    with np.load(parent/'trajectory.npz') as a:tick=int(a['tick'][-1])
    return dict(kind='recorded_parent_terminal_positions',parent_run=str(parent.resolve()),parent_tick=tick,
                parent_trajectory_sha256=hashlib.sha256((parent/'trajectory.npz').read_bytes()).hexdigest(),
                parent_evaluation_sha256=hashlib.sha256((parent/'evaluation.json').read_bytes()).hexdigest(),
                initialization='Independent new simulation at recorded positions with zero initial velocities; not a continued physical checkpoint.')
