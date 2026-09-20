from fixtures_v4.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);s=c.cfg['task_spec'];x,y=s['fixture']['center_xy']
    i=c.select_reachable([s['primary_corner'],188,20,335]);c.acquire(i);c.lift_clear()
    c.rec.phase='basket_transfer';c.move([x,y,1.28]);c.mark('above_basket');c.move([x,y,1.02]);c.mark('lowered_into_basket');c.release();c.hold(robot,rec,3.);c.mark('released_in_basket');c.finish()
