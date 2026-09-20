from folding_v3.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);c.fold();c.finish()
