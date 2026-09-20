"""Re-observed corner pulls towards the marked target region."""
from tabletop_v2.actions import Controller

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner)
    # In the reverse-fold variant, two pulls can move the largest-error corner
    # beyond the arm's approach workspace. Probe remaining corners before moving.
    probe_after=2 if c.cfg['task_spec']['variant_id']=='v003' else None
    c.spread(6,min_pulls=2,probe_after_pulls=probe_after);c.mark('spread_complete');c.finish()
