"""Load the rod slowly, release onto its support, then regrasp both hems."""
import numpy as np
from fixtures_v4.actions import Controller
from fixtures_v4.metrics import measure


def crown_candidates(vertices,group,fixture):
    """Select the currently supported crown hem, excluding high free flaps."""
    v=np.asarray(vertices);y=fixture['center_xy'][1];z=fixture['center_height_m'];r=fixture['radius_m']
    candidates=[i for i in group if v[i,2]>=z and np.linalg.norm(v[i,[1,2]]-[y,z])<=r+.015]
    return sorted(candidates,key=lambda i:float(v[i,2]),reverse=True)


def observed_boundary_candidates(vertices,topology,fixture,side,used=()):
    """Reobserve spatial hems after a drape rotates; do not assume material axes."""
    edges={}
    for face in topology['faces']:
        for a,b in zip(face,face[1:]+face[:1]):
            edge=tuple(sorted((a,b)));edges[edge]=edges.get(edge,0)+1
    boundary={i for edge,count in edges.items() if count==1 for i in edge}
    rest=np.asarray(topology['rest_vertices']);v=np.asarray(vertices)
    candidates=crown_candidates(v,boundary,fixture)
    # Two strokes must act on separate material regions, even after folding.
    candidates=[i for i in candidates if all(np.linalg.norm(rest[i]-rest[j])>=.10 for j in used)]
    return sorted(candidates,key=lambda i:(-side*float(v[i,0]),-float(v[i,2])))


def execute(robot,rec,planner):
    from safety import Halted
    c=Controller(robot,rec,planner);s=c.cfg['task_spec'];f=s['fixture'];x,y=f['center_xy']
    top=f['center_height_m']+f['radius_m']
    clamp=s.get('rod_clamp',{})
    if clamp.get('enabled'):c.scene.fixture_trace=(rec.out/'fixture_constraints.jsonl').open('x')
    c.mark('rod_sequence_revision',version=3 if clamp.get('enabled') else 2,description=('Slow supported feed, first hem to visible local clamp, opposite hem spread, fixture-assisted terminal hold' if clamp.get('enabled') else 'Slow supported feed, release, separate lateral hem regrasp strokes, free hanging hold'))
    i=c.select_reachable([s['primary_corner'],188,20,335]);c.acquire(i);c.lift_clear();c.mark('cloth_lifted')
    c.rec.phase='approach_rod';c.move([x,y-.16,1.27]);c.move([x,y-.09,top+.125])
    # Each small transit is an executed cuRobo path. The hand keeps holding the
    # leading material while the trailing cloth comes into contact with the rod.
    c.rec.phase='feed_onto_rod';c.mark('rod_feed_started')
    # Earlier 13--15 cm feed left a short far tail that slid back during the
    # first regrasp. Approximate a balanced half span over the rod quarter arc.
    rest=np.asarray(c.scene.topology['rest_vertices']);span=float(np.ptp(rest[:,:2],axis=0).max())
    straight=span/2-np.pi*f['radius_m']/2
    far=float(np.sqrt(straight**2-(f['center_height_m']-.94)**2))
    c.rec.mark('rod_feed_distance_selection',nominal_m=s['initial_parameters']['rod_far_offset_m'],
               executed_m=far,reason='Half cloth span minus rod arc, projected to the held edge height; verify actual support after release')
    for dy,height in [(-.035,top+.085),(.035,top+.075),(far,top+.065)]:
        c.move([x,y+dy,height]);c.hold(robot,rec,.4);c.mark('rod_feed_increment')
    c.mark('crossed_rod');c.move([x,y+far,.94]);c.hold(robot,rec,1.)
    if measure(c.scene.cloth_vertices(),c.scene.topology,c.cfg)['rod_contact_band_fraction']<.015:
        raise Halted('Feed did not put cloth onto rod support; no release or spreading claim')
    c.mark('rod_loaded');c.release();c.hold(robot,rec,2.);c.mark('released_on_rod');c.retreat()
    c.mark('rod_supported')

    if clamp.get('enabled'):
        spread_with_fixture(c)
        return

    used=[]
    for side in [-1,1]:
        def observe_crown():
            candidates=observed_boundary_candidates(c.scene.cloth_vertices(),c.scene.topology,f,side,used)
            if not candidates:raise Halted('No observed crown hem for the next supported spreading stroke')
            c.rec.mark('rod_crown_observation',side=side,vertex_indices=candidates,
                       reason='Current spatial boundary supported by the rod; exclude previously pulled material region')
            return candidates
        index=c.acquire(None,reselect=observe_crown)
        used.append(index)
        c.rec.phase='spread_on_rod';p=c.tcp();height=top+.018
        target=x+side*.13
        c.mark('rod_spread_started',side=side,vertex_index=int(index),target_x_m=target,
               support_clearance_m=.018,reason='Maintain the validated rod pinch clearance during lateral motion; extra lift carried the entire drape')
        c.move([float(p[0]),y,height])
        for xx in np.linspace(float(p[0]),target,4)[1:]:
            c.move([float(xx),y,height])
        c.release();c.hold(robot,rec,1.);c.mark('rod_side_spread',side=side,vertex_index=int(index),target_x_m=target)
        c.retreat()
    c.mark('rod_spread_complete');c.finish()


def spread_with_fixture(c, *, sides=(-1,1), initial_used=()):
    """Sequential supported strokes with one explicitly recorded fixed local hold."""
    from safety import Halted
    f=c.cfg['task_spec']['fixture'];clamp=c.cfg['task_spec']['rod_clamp']
    x,y=f['center_xy'];top=f['center_height_m']+f['radius_m'];used=list(initial_used)
    for side in sides:
        def observe():
            candidates=observed_boundary_candidates(c.scene.cloth_vertices(),c.scene.topology,f,side,used)
            if side>0 and used:
                rest=np.asarray(c.scene.topology['rest_vertices']);length_axis=int(np.argmax(np.ptp(rest[:,:2],axis=0)))
                candidates.sort(key=lambda i:abs(float(rest[i,length_axis]-rest[used[0],length_axis])))
            if not candidates:raise Halted('No distinct supported boundary for fixture-assisted spreading')
            c.rec.mark('rod_crown_observation',side=side,vertex_indices=candidates,
                       reason='Observed rod-supported boundary; opposite hem prioritized by material alignment with the held hem to avoid a diagonal rod fold')
            return candidates
        index=c.acquire(None,reselect=observe);used.append(index)
        c.rec.phase='spread_on_rod';p=c.tcp()
        target=clamp['capture_center_world_m'][0] if side<0 else x+.13
        c.mark('rod_spread_started',side=side,vertex_index=int(index),target_x_m=target,
               fixture_assisted=side>0,support_clearance_m=.018)
        # A 10 mm raised feed cleared the intermediate endpoint rejected at
        # the rod pinch height. Probe every waypoint in the complete scene
        # before moving, then lower back into the mouth for local capture.
        height=top+(.028 if side<0 else .018)
        route=[[float(p[0]),y,height]]+[[float(xx),y,height] for xx in np.linspace(float(p[0]),target,5)[1:]]
        if side<0:route.append([target,y,top+.018])
        probe_q=c.robot.state()[0]['joints']
        for goal in route:
            result=c.planner.call(dict(q=probe_q,tcp_world=goal,quaternion_wxyz=c.rotation.as_quat()[[3,0,1,2]].tolist()))
            c.rec.mark('corner_approach_probe',vertex_index=int(index),goal=goal,planner_id=c.planner.count,
                       success=bool(result.get('success')),status=result.get('status'),
                       reason='Unexecuted complete supported feed route to visible clamp or opposite hem; original collision geometry retained')
            if not result.get('success'):raise Halted('Supported fixture feed route failed preflight: '+str(result.get('status')))
            probe_q=result['q'][-1]
        c.rec.mark('fixture_feed_route',side=side,waypoints=route,reason='Raised first feed by 10 mm after observed intermediate IK rejection; descend again before capture')
        for goal in route:c.move(goal)
        c.hold(c.robot,c.rec,.6)
        if side<0:
            attachment=c.scene.attach_fixture_patch(index,transfer_from_gripper=True)
            c.rec.mark('assisted_grasp_released',transfer_to_fixture=True)
            c.rec.mark('fixture_grasp_attached',**attachment)
            c.motion({'gripper':'open'},c.robot,c.rec,c.planner,gripper_width=.035)
            c.hold(c.robot,c.rec,.6)
        else:c.release()
        c.mark('rod_side_spread',side=side,vertex_index=int(index),target_x_m=target)
        c.retreat()
    c.mark('rod_spread_complete',fixture_assisted=True)
    c.rec.mark('fixture_assisted_terminal',free_bare_rod_hanging_claimed=False,
               vertex_ids=c.scene.fixture_patch['ids'].tolist())
    c.finish()
