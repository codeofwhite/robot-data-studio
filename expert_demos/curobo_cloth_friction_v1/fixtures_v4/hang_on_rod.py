from fixtures_v4.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);s=c.cfg['task_spec'];f=s['fixture'];x,y=f['center_xy']
    i=c.select_reachable([s['primary_corner'],188,20,335]);c.acquire(i);c.lift_clear();c.mark('cloth_lifted')
    c.rec.phase='approach_rod';c.move([x,y-.16,1.27]);c.move([x,y+.045,1.24]);c.move([x,y+s['initial_parameters']['rod_far_offset_m'],1.16]);c.mark('crossed_rod')
    c.rec.phase='drape_rod';c.move([x,y+s['initial_parameters']['rod_far_offset_m'],.92]);c.release();c.hold(robot,rec,3.);c.mark('released_on_rod');c.finish()
