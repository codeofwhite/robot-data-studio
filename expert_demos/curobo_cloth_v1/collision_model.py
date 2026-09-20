"""Conservative sphere cover of the actual MJCF finger contact pad boxes."""
import numpy as np
def pad_spheres(side):
    half=np.array([.0085,.004,.009]);n=np.array([5,2,5]);cell=2*half/n
    radius=float(np.linalg.norm(cell/2))
    axes=[np.linspace(-h+c/2,h-c/2,int(k)) for h,c,k in zip(half,cell,n)]
    centre=np.array([0.,side*.004,.0445])
    return [{'center':(centre+[x,y,z]).tolist(),'radius':radius} for x in axes[0] for y in axes[1] for z in axes[2]]
def calibrated_robot_config(rc,loader,config_root):
    import copy
    rc=copy.deepcopy(rc);k=rc['kinematics']
    spheres=loader(str(config_root/k['collision_spheres']))['collision_spheres']
    for name,side in [('panda_leftfinger',1),('panda_rightfinger',-1)]:
        # Retain conservative proximal visual-body sphere; replace distal sphere by a
        # mathematically covering grid of the actual physical contact pad.
        proximal=[dict(center=[0.,side*.02,.015],radius=.015)]
        spheres[name]=pad_spheres(side)+proximal
    k['collision_spheres']=spheres
    k['collision_sphere_buffer']={name:(0. if 'finger' in name else .004) for name in k['collision_link_names']}
    return rc
