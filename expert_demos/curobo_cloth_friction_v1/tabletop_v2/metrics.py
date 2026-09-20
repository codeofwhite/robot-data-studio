"""Task-specific, coarse visual-demo diagnostics from recorded physical states."""
import numpy as np
from scipy.spatial import ConvexHull


def measure(vertices, topology, cfg):
    v=np.asarray(vertices);spec=cfg['task_spec'];nx,ny=topology['physical_grid']
    ids=[0,nx-1,(ny-1)*nx,nx*ny-1]
    goal=np.array([spec['target_corners_xy_m'][str(i)] for i in ids])
    lo,hi=np.array(spec['target_region_xy_m']);height=v[:,2]-cfg['table_height']
    inside=((v[:,:2]>=lo)&(v[:,:2]<=hi)).all(axis=1)
    area=ConvexHull(v[:,:2]).volume if np.linalg.matrix_rank(v[:,:2]-v[:,:2].mean(0))==2 else 0.
    mesh=v.reshape(ny,nx,3);axis=mesh[:,-1,:2].mean(0)-mesh[:,0,:2].mean(0)
    yaw=np.rad2deg(np.arctan2(axis[1],axis[0]));error=(yaw-spec['target_yaw_deg']+180)%360-180
    primary=spec['primary_corner'];opposite=nx*ny-1-primary
    return dict(target_surface_fraction=float((inside&(height>=-.001)&(height<=.03)).mean()),
                on_table_xy_fraction=float(inside.mean()), projected_area_fraction=float(area/topology['flat_area_m2']),
                height_p95_m=float(np.percentile(height,95)), hanging_fraction=float((height<-.02).mean()),
                center_error_m=float(np.linalg.norm(v[:,:2].mean(0)-np.array(spec['target_center_world_m'][:2]))),
                angle_error_deg=float(abs(error)), yaw_deg=float(yaw),
                corner_errors_m={str(i):float(np.linalg.norm(v[i,:2]-g)) for i,g in zip(ids,goal)},
                primary_diagonal_xy_m=float(np.linalg.norm(v[primary,:2]-v[opposite,:2])))


def satisfactory(m, task):
    common=m['target_surface_fraction']>=.90 and m['projected_area_fraction']>=.78 and m['height_p95_m']<=.03
    if task=='translate_rotate_align':
        return common and m['center_error_m']<=.05 and m['angle_error_deg']<=12 and max(m['corner_errors_m'].values())<=.05
    if task=='unfold_corner':return common and m['primary_diagonal_xy_m']>=.44
    return common and m['center_error_m']<=.07


def task_result(data, events, topology, cfg):
    task=cfg['task_id'];spec=cfg['task_spec'];names=[e['name'] for e in events]
    required=spec['required_stages'];complete=all(x in names for x in required)
    start=next((e['tick'] for e in events if e['name']=='task_start'),0)
    ix=int(np.flatnonzero(data['tick']==start)[0])
    initial=measure(data['cloth_vertices'][ix],topology,cfg)
    final=measure(data['cloth_vertices'][-1],topology,cfg)
    if task=='edge_retrieve_spread':valid=initial['hanging_fraction']>=.20
    elif task=='directed_flatten':valid=initial['projected_area_fraction']<.94 or initial['height_p95_m']>.012
    elif task=='translate_rotate_align':valid=initial['angle_error_deg']>8 or initial['center_error_m']>.025
    else:valid=initial['primary_diagonal_xy_m']<.465
    gains={'area_gain':final['projected_area_fraction']-initial['projected_area_fraction'],
           'angle_improvement_deg':initial['angle_error_deg']-final['angle_error_deg'],
           'diagonal_gain_m':final['primary_diagonal_xy_m']-initial['primary_diagonal_xy_m']}
    effective=(final['hanging_fraction']<.03 if task=='edge_retrieve_spread' else
               gains['area_gain']>.015 or final['height_p95_m']<initial['height_p95_m']-.003 if task=='directed_flatten' else
               gains['angle_improvement_deg']>3 or final['center_error_m']<initial['center_error_m']-.015 if task=='translate_rotate_align' else
               gains['diagonal_gain_m']>.035)
    adjusted_corners={e.get('vertex_index') for e in events if e['name']=='corner_adjusted'}
    return dict(initial=initial,final=final,changes=gains,distinct_adjusted_corners=len(adjusted_corners),assessment_scope='Task-specific visual-demo diagnostics; manual frame review remains separate'),dict(
        task_initial_condition=bool(valid),task_stages_complete=complete,
        task_stages_in_order=complete and [names.index(x) for x in required]==sorted(names.index(x) for x in required),
        action_executed=names.count('contact_grasp_verified')>0,
        visible_task_effect=bool(effective),task_goal_reached=bool(satisfactory(final,task)),
        requested_corner_sequence=task not in ('directed_flatten','translate_rotate_align') or len(adjusted_corners)>=2)
