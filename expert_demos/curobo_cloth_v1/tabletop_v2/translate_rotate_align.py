"""Align material corner correspondences to a translated, rotated goal."""
from tabletop_v2.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);c.spread(8,min_pulls=2);c.mark('alignment_complete');c.finish()
