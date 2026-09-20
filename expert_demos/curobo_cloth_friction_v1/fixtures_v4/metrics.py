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


def task_result(data,events,topology,cfg):
    task=cfg['task_id'];spec=cfg['task_spec'];names=[e['name'] for e in events];required=spec['required_stages']
    start=next((e['tick'] for e in events if e['name']=='task_start'),0);ix=int(np.flatnonzero(data['tick']==start)[0])
    initial=measure(data['cloth_vertices'][ix],topology,cfg);final=measure(data['cloth_vertices'][-1],topology,cfg)
    initial_ok=(satisfactory(initial,'hang_on_rod') if task=='retrieve_from_rod' else initial['inside_basket_fraction']>=.65 if task=='retrieve_from_basket' else not satisfactory(initial,task))
    complete=all(x in names for x in required);moves=[e for e in events if e['name']=='planned_waypoint'];adjusted={e['vertex_index'] for e in events if e['name']=='corner_adjusted'}
    released=[e['tick'] for e in events if e['name']=='contact_grasp_released'];hold=(int(data['tick'][-1])-released[-1])*cfg['dt'] if released else 0.
    return dict(initial=initial,final=final,distinct_adjusted_corners=len(adjusted),released_terminal_seconds=hold,
                assessment_scope='Fixture-relative visual-demo diagnostics, with separate saved-frame inspection; retrieval center error is descriptive, without an alignment requirement'),dict(
        task_initial_condition=bool(initial_ok),task_stages_complete=complete,
        task_stages_in_order=complete and [names.index(x) for x in required]==sorted(names.index(x) for x in required),
        task_goal_reached=bool(satisfactory(final,task)),action_executed=bool(moves) and 'contact_grasp_verified' in names,
        released_terminal_hold=hold>=2.,requested_spreading=not task.startswith('retrieve_') or len(adjusted)>=2)
