import numpy as np
from folding_v3.actions import Controller
from folding_v3.metrics import garment_measure,measure,satisfactory

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);g=c.scene.topology['garment'];keys=g['keypoints']
    initial=c.scene.cloth_vertices().copy();center=initial[:,:2].mean(0)
    desired=initial[:,:2].copy();desired[:,1]=2*center[1]-desired[:,1]
    # Clear the entire garment before laying it down. A vertical descent after
    # horizontal transport bunched it beneath the fingers in the first trials.
    index=keys['left_hem'];c.acquire(index,kind='garment_hem');c.mark('garment_acquired')
    c.rec.phase='garment_turn';p=c.tcp();c.move([p[0],p[1],1.30])
    v=c.scene.cloth_vertices();low=int(np.argmin(v[:,2]));p=c.tcp()
    shift=desired[low]-v[low,:2]
    c.move([*(p[:2]+shift),p[2]])
    v=c.scene.cloth_vertices();p=c.tcp()
    drop=max(0.,float(v[:,2].min()-c.cfg['table_height']-.008))
    c.move([p[0],p[1],p[2]-drop]);start=c.tcp()
    c.mark('garment_trailing_edge_positioned',material_vertex=low,target_xy=desired[low].tolist())
    end=np.r_[desired[index],c.cfg['table_height']+.022]
    for fraction in [.25,.5,.75,1.]:c.move(start+(end-start)*fraction)
    c.release();c.mark('garment_turned')
    for key,panel in [('right_hem','body'),('left_hem','body'),('neck_upper','body'),
                      ('left_cuff_upper','left_sleeve'),('right_cuff_upper','right_sleeve')]:
        v=c.scene.cloth_vertices();quality=measure(v,c.scene.topology,c.cfg)
        if satisfactory(quality,'garment_flip'):break
        idx=keys[key]
        if np.linalg.norm(v[idx,:2]-desired[idx])<.025 and quality['front_panel_normal_z'][panel]<=-.35:continue
        c.pull(idx,desired[idx],.07)
    c.mark('garment_spread');c.finish()
