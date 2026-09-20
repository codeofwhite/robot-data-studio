"""Recover the hanging half by pulling the supported corner inward."""
from tabletop_v2.actions import Controller
from tabletop_v2.metrics import measure,satisfactory
import numpy as np

def execute(robot,rec,planner):
    c=Controller(robot,rec,planner);spec=c.cfg['task_spec'];index=spec['primary_corner']
    c.pull(index,spec['target_corners_xy_m'][str(index)],clearance=.045)
    c.mark('edge_recovered')
    # Original-scene cuRobo probes at both travel and release heights reject
    # front-edge goal 0 and left-edge goal 20. The cloth can still reach the
    # unchanged target rectangle by pulling its other corners.
    excluded=20 if spec['variant_id']=='v002' else 0
    targets={int(k):np.asarray(v) for k,v in spec['target_corners_xy_m'].items() if int(k)!=excluded}
    c.mark('spread_strategy',deferred_corner=excluded,reason='Target outside cuRobo reachable set at travel and release heights',
           candidate_corners=list(targets),diagnostic='tabletop_v2/diagnostics/edge_retrieve_spread/'+('v002' if excluded==20 else 'v001')+'/target_reachability.json')
    corrected=set()
    for _ in range(4):
        if corrected and satisfactory(measure(c.scene.cloth_vertices(),c.scene.topology,c.cfg),c.cfg['task_id']):break
        if len(corrected)==len(targets):corrected.clear()
        vertices=c.scene.cloth_vertices()
        corner=max((i for i in targets if i not in corrected),key=lambda i:np.linalg.norm(vertices[i,:2]-targets[i]))
        c.pull(corner,targets[corner]);corrected.add(corner)
    c.mark('spread_complete');c.finish()
