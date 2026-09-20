import numpy as np
from fixtures_v4.actions import Controller,grasp_position

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);s=c.cfg['task_spec'];f=s['fixture'];x,y=f['center_xy']
    i=c.select_reachable([s['primary_corner'],168,0,315]);c.acquire(i);c.lift_clear(.98)
    # Keep trailing material supported while crossing the connected L-table.
    # Fully suspending it first produced a narrow pile instead of a broad cover.
    c.rec.phase='cover_transfer';c.move([x,.16,1.00]);c.move([x,y,1.03]);c.mark('above_box')
    c.move([x,y-.19,.94]);c.move([x,y-.19,.817])
    # The reverse fold deposited its center about 2 cm to the right. Reobserve
    # while still holding the edge and translate laterally before releasing.
    # Only the gripper moves; cloth positions remain solver-controlled.
    center=c.scene.cloth_vertices().mean(axis=0);dx=float(np.clip(x-center[0],-.03,.03))
    if abs(dx)>.001:
        p=c.tcp();goal=[float(p[0]+dx),float(p[1]),float(p[2])]
        c.rec.mark('deposit_centering_planned',observed_center=center.tolist(),correction_x_m=dx,
                   maximum_correction_m=.03,goal=goal,reason='Observed lateral offset from box center before release')
        c.move(goal);c.mark('deposit_centered')
    c.release();c.mark('draped_over_box')
    corrected=set()
    # Two small hem adjustments complete the requested action. The previous
    # extra two corrections pulled an off-center cover progressively farther.
    for count in range(2):
        # The 30 x 40 cm sheet must spend material length descending the box.
        # Pulling its corners to the flat-table rectangle removed a valid cover.
        # Tidy the exterior rear hems first with a short outward stroke instead.
        chosen=c.select_reachable([i for i in [335,20,0,315] if i not in corrected])
        c.acquire(chosen);c.rec.phase='cover_adjust';p=c.tcp()
        point=c.scene.cloth_vertices()[chosen].copy();direction=point[:2]-[x,y]
        length=float(np.linalg.norm(direction))
        if length<1e-6:raise ValueError('A box-center material point has no outward hem direction')
        target=point[:2]+.02*direction/length
        release=grasp_position([*target,float(point[2])],c.cfg)
        height=max(c.cfg['table_height']+.035,p[2]+.010,release[2])
        c.rec.mark('hem_tidy_planned',vertex_index=chosen,target_xy=target.tolist(),stroke_m=.02,
                   reason='Preserve three-dimensional drape; do not pull to the flat-table rectangle')
        c.move([p[0],p[1],height]);c.move([*target,height]);c.move(release);c.release()
        c.mark('corner_adjusted',vertex_index=chosen,target_xy=target.tolist(),strategy='outward_hem_tidy',stroke_m=.02)
        corrected.add(chosen)
    c.mark('cover_adjusted');c.finish()
