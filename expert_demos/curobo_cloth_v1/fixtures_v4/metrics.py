"""Fixture-relative task evidence computed from actual simulated material points."""
import numpy as np
from scipy.spatial import ConvexHull


def box_top_coverage(v,faces,fixture):
    x,y=fixture['center_xy'];w,d,h=fixture['size_m'];top=fixture['base_height_m']+h
    points=np.array([[xx,yy] for xx in np.linspace(x-w*.48,x+w*.48,15) for yy in np.linspace(y-d*.48,y+d*.48,13)])
    covered=np.zeros(len(points),bool)
    for tri in v[np.asarray(faces,int)]:
        a,b,c=tri;u=b[:2]-a[:2];q=c[:2]-a[:2];den=u[0]*q[1]-u[1]*q[0]
        if abs(den)<1e-10:continue  # Vertical faces have no projected top area.
        r=points-a[:2];s=(r[:,0]*q[1]-r[:,1]*q[0])/den;t=(u[0]*r[:,1]-u[1]*r[:,0])/den
        z=a[2]+s*(b[2]-a[2])+t*(c[2]-a[2])
        covered|=(s>=0)&(t>=0)&(s+t<=1)&(z>=top-.003)&(z<=top+.03)
    return float(covered.mean())


def measure(vertices,topology,cfg):
    v=np.asarray(vertices);spec=cfg['task_spec'];f=spec['fixture'];x,y=f['center_xy'];z=cfg['table_height']
    lo,hi=np.asarray(spec['target_region_xy_m']);inside=((v[:,:2]>=lo)&(v[:,:2]<=hi)).all(1)
    area=ConvexHull(v[:,:2]).volume if np.linalg.matrix_rank(v[:,:2]-v[:,:2].mean(0))==2 else 0.
    m=dict(center_world_m=v.mean(0).tolist(),projected_area_fraction=float(area/topology['flat_area_m2']),
           target_surface_fraction=float((inside&(v[:,2]>=z-.001)&(v[:,2]<=z+.035)).mean()),
           height_p95_m=float(np.percentile(v[:,2]-z,95)),
           center_error_m=float(np.linalg.norm(v[:,:2].mean(0)-spec['target_center_world_m'][:2])))
    if f['kind']=='rod':
        rz=f['center_height_m'];r=f['radius_m'];within=np.abs(v[:,0]-x)<f['length_m']/2
        dist=np.linalg.norm(v[:,[1,2]]-[y,rz],axis=1)
        m.update(rod_contact_band_fraction=float((within&(dist<r+.025)&(v[:,2]>rz-.03)).mean()),
                 near_tail_fraction=float((within&(v[:,1]<y-.025)&(v[:,2]<rz-.04)).mean()),
                 far_tail_fraction=float((within&(v[:,1]>y+.025)&(v[:,2]<rz-.04)).mean()),
                 above_table_fraction=float((v[:,2]>z+.015).mean()))
        crown=v[within&(dist<r+.025)&(v[:,2]>rz-.03),0]
        m['rod_supported_width_m']=float(np.ptp(crown)) if len(crown)>1 else 0.
    elif f['kind']=='basket':
        w,d,h=f['size_m'];t=f['wall_m'];bottom=f['base_height_m']+t;rim=f['base_height_m']+h
        xy=(np.abs(v[:,0]-x)<w/2-t+.002)&(np.abs(v[:,1]-y)<d/2-t+.002)
        m.update(inside_basket_fraction=float((xy&(v[:,2]>=bottom-.002)&(v[:,2]<rim)).mean()),
                 above_rim_fraction=float((v[:,2]>rim+.005).mean()))
    else:
        w,d,h=f['size_m'];top=f['base_height_m']+h;low=v[:,2]<top-.02
        sides=[np.any(low&(v[:,0]<x-w/2)),np.any(low&(v[:,0]>x+w/2)),np.any(low&(v[:,1]<y-d/2)),np.any(low&(v[:,1]>y+d/2))]
        m.update(box_top_coverage=box_top_coverage(v,topology['faces'],f),draping_sides=int(sum(sides)))
    return m


def satisfactory(m,task):
    if task=='hang_on_rod':return m['rod_contact_band_fraction']>=.015 and min(m['near_tail_fraction'],m['far_tail_fraction'])>=.10 and m['above_table_fraction']>=.85
    if task=='place_in_basket':return m['inside_basket_fraction']>=.80
    if task=='cover_box':return m['box_top_coverage']>=.80 and m['draping_sides']>=3
    # Retrieval requests placement on the receiving table and opening, without
    # the marked-center alignment required by the separate tabletop task.
    return m['target_surface_fraction']>=.88 and m['projected_area_fraction']>=.72


def rod_sequence_complete(events):
    """A terminal drape alone cannot stand in for the requested regrasp sequence."""
    names=[e['name'] for e in events]
    required=['rod_feed_started','rod_loaded','released_on_rod','rod_supported','rod_spread_started','rod_side_spread','rod_spread_complete','task_complete']
    if not all(name in names for name in required):return False
    if [names.index(name) for name in required]!=sorted(names.index(name) for name in required):return False
    strokes=[e for e in events if e['name']=='rod_side_spread']
    revision=max((e.get('version',0) for e in events if e['name']=='rod_sequence_revision'),default=0)
    if revision>=3:
        if names.count('fixture_grasp_attached')!=1 or 'fixture_assisted_terminal' not in names:return False
        first=next((i for i,e in enumerate(events) if e['name']=='rod_side_spread' and e.get('side')==-1),None)
        second=next((i for i,e in enumerate(events) if e['name']=='rod_spread_started' and e.get('side')==1),None)
        if first is None or second is None or not names.index('fixture_grasp_attached')<first<second:return False
        if any(e.get('free_bare_rod_hanging_claimed') is not False for e in events if e['name']=='fixture_assisted_terminal'):return False
    return (any(e['name']=='rod_sequence_revision' and e.get('version',0)>=2 for e in events)
            and {e.get('side') for e in strokes}=={-1,1}
            and len({e.get('vertex_index') for e in strokes})>=2
            and names.count('assisted_grasp_attached')>=3 and names.count('assisted_grasp_released')>=3)


def task_result(data,events,topology,cfg):
    task=cfg['task_id'];spec=cfg['task_spec'];names=[e['name'] for e in events];required=spec['required_stages']
    start=next((e['tick'] for e in events if e['name']=='task_start'),0);ix=int(np.flatnonzero(data['tick']==start)[0])
    initial=measure(data['cloth_vertices'][ix],topology,cfg);final=measure(data['cloth_vertices'][-1],topology,cfg)
    initial_ok=(satisfactory(initial,'hang_on_rod') if task=='retrieve_from_rod' else initial['inside_basket_fraction']>=.65 if task=='retrieve_from_basket' else not satisfactory(initial,task))
    complete=all(x in names for x in required);moves=[e for e in events if e['name']=='planned_waypoint'];adjusted={e['vertex_index'] for e in events if e['name']=='corner_adjusted'}
    released=[e['tick'] for e in events if e['name']=='assisted_grasp_released'];hold=(int(data['tick'][-1])-released[-1])*cfg['dt'] if released else 0.
    rod_support=None
    if task=='hang_on_rod':
        supported=next((e for e in events if e['name']=='rod_supported'),None)
        if supported:
            at=np.flatnonzero(data['tick']==supported['tick'])
            if len(at)==1:rod_support=measure(data['cloth_vertices'][int(at[0])],topology,cfg)
    return dict(initial=initial,final=final,distinct_adjusted_corners=len(adjusted),released_terminal_seconds=hold,
                rod_support_before_spreading=rod_support,fixture_assistance=spec.get('rod_clamp',{}),
                terminal_support='rod_with_local_fixture_assistance' if spec.get('rod_clamp',{}).get('enabled') else 'contact_support',
                assessment_scope='Fixture-relative visual-demo diagnostics, with separate saved-frame inspection; retrieval center error is descriptive, without an alignment requirement'),dict(
        task_initial_condition=bool(initial_ok),task_stages_complete=complete,
        task_stages_in_order=complete and [names.index(x) for x in required]==sorted(names.index(x) for x in required),
        task_goal_reached=bool(satisfactory(final,task)),action_executed=bool(moves) and 'assisted_grasp_attached' in names,
        released_terminal_hold=hold>=2.,requested_spreading=not task.startswith('retrieve_') or len(adjusted)>=2,
        rod_supported_spreading=task!='hang_on_rod' or bool(rod_sequence_complete(events) and rod_support and rod_support['rod_contact_band_fraction']>=.015))


def fixture_trace_audit(cfg,events,fixture_rows,gripper_rows,ticks,vertices,physics_rows=None):
    """Validate ownership and capture using saved states, not the success label."""
    clamp=cfg['task_spec'].get('rod_clamp',{})
    if not clamp.get('enabled'):return {'enabled':False}
    def require(condition,message):
        if not condition:raise ValueError(message)
    captures=[e for e in events if e['name']=='fixture_grasp_attached']
    require(len(captures)==1,'Exactly one local fixture capture is required')
    e=captures[0];ids=e['vertex_ids'];aim=np.asarray(e['aim_positions_world_m'])
    require(len(ids)==1 and aim.shape==(1,3),'Fixture capture must hold one node')
    require(np.linalg.norm(aim[0]-clamp['capture_center_world_m'])<=clamp['capture_radius_m'],'Capture outside visible mouth')
    require(e.get('transferred_from_gripper') is True,'Missing recorded gripper-to-fixture transfer')
    require(len(fixture_rows)>0,'Empty fixture trace')
    tick_rows=[r['tick'] for r in fixture_rows];require(len(tick_rows)==len(set(tick_rows)),'Duplicate fixture tick')
    require(tick_rows==list(range(tick_rows[0],int(ticks[-1])+1)),'Fixture trace is not continuous through terminal hold')
    require(tick_rows[0]<=e['tick'],'Fixture capture precedes its trace')
    grips={r['tick']:r for r in gripper_rows};by_tick={r['tick']:r for r in fixture_rows};errors=[]
    for r in fixture_rows:
        active=r['tick']>e['tick']
        require(r['active']==active,'Fixture state disagrees with capture event')
        require(r['strength_rate']==cfg['assisted_grasp']['strength_rate'],'Fixture strength differs from approved solver strength')
        require(r['vertex_ids']==(ids if active else []),'Fixture ownership changed or exceeds one node')
        require(np.array_equal(np.asarray(r['aim_positions_world_m']),aim if active else np.asarray([])),'Fixture target changed')
        require(not set(r['vertex_ids'])&set(grips.get(r['tick'],{}).get('vertex_ids',[])),'Double gripper/fixture ownership')
    for i,tick in enumerate(ticks):
        r=by_tick.get(int(tick))
        if r and r['active']:errors.append(float(np.linalg.norm(vertices[i,ids[0]]-aim[0])))
        if tick==e['tick']:require(np.linalg.norm(vertices[i,ids[0]]-aim[0])<2e-6,'Capture target differs from actual node')
    require(bool(errors),'No recorded fixture-held state')
    require(any(e['name']=='fixture_assisted_terminal' and e.get('free_bare_rod_hanging_claimed') is False for e in events),'Fixture terminal disclosure missing')
    step_errors=[]
    if physics_rows is not None:
        for tick,r in by_tick.items():
            actual=physics_rows[tick]['cloth_health']['fixture_constraint_after_step']
            require(actual['active']==r['active'] and actual['vertex_ids']==r['vertex_ids'],'Physical fixture ownership differs from applied trace')
            require(actual['aim_positions_world_m']==r['aim_positions_world_m'],'Physical fixture target differs from applied trace')
            if r['active']:
                error=np.linalg.norm(np.asarray(actual['actual_positions_world_m'])-aim,axis=1)
                require(np.allclose(error,actual['error_m'],atol=1e-9),'Recorded fixture error disagrees with positions')
                step_errors.extend(map(float,error))
        for i,tick in enumerate(ticks):
            if tick in by_tick and by_tick[int(tick)]['active']:
                actual=physics_rows[int(tick)]['cloth_health']['fixture_constraint_after_step']
                require(np.allclose(vertices[i,ids],actual['actual_positions_world_m'],atol=2e-7),'Fixture step positions disagree with trajectory')
    return dict(enabled=True,vertex_ids=ids,capture_tick=e['tick'],capture_distance_m=float(np.linalg.norm(aim[0]-clamp['capture_center_world_m'])),
        max_constraint_error_m=max(errors),p95_constraint_error_m=float(np.percentile(errors,95)),
        recorded_active_samples=len(errors),recorded_active_physics_ticks=len(step_errors),
        maximum_step_constraint_error_m=max(step_errors) if step_errors else None,terminal_fixture_active=True,free_bare_rod_hanging_claimed=False)
