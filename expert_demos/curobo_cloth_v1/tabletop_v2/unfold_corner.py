"""Lift the inward-folded material corner, flip it outwards and release."""
from tabletop_v2.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);spec=c.cfg['task_spec'];index=spec['primary_corner']
    c.pull(index,spec['target_corners_xy_m'][str(index)],clearance=.075)
    c.mark('corner_unfolded');c.finish()
