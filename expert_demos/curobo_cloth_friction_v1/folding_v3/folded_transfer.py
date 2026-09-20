import numpy as np
from scipy.spatial.transform import Rotation
from folding_v3.actions import Controller, acquisition_patch_diameter
from folding_v3.metrics import measure, fold_satisfactory

def folded_destination(topology,spec):
    nx,ny=topology['physical_grid'];ids=np.arange(nx*ny);row=ids//nx;col=ids%nx
    targets=spec['target_corners_xy_m'];a=np.asarray(targets['0']);b=np.asarray(targets[str(nx-1)]);d=np.asarray(targets[str((ny-1)*nx)])
    return a+(d-a)*row[:,None]/(ny-1)+(b-a)*np.minimum(col,nx-1-col)[:,None]/(nx-1)

def transfer_grasp_candidates(vertices,topology):
    # Holding one end of the open edge lets the unsupported far corner peel
    # apart. Try a balanced middle-edge pinch first, still only two local nodes.
    nx,ny=topology['physical_grid']
    rows=list(dict.fromkeys([(ny-1)//2,ny//2,0,ny-1]))
    pairs=[(row*nx,row*nx+nx-1) for row in rows]
    pairs=[pair for pair in pairs if np.linalg.norm(vertices[pair[0]]-vertices[pair[1]])<=.04]
    return sorted(pairs,key=lambda pair:(abs(pair[0]//nx-(ny-1)/2),
                                        np.linalg.norm(vertices[pair[0]]-vertices[pair[1]])))

def transfer_patch_candidates(vertices,topology):
    """Two corresponding open-edge pairs in adjacent material rows."""
    nx,ny=topology['physical_grid'];candidates=[]
    for row in range(ny-1):
        ids=(row*nx,row*nx+nx-1,(row+1)*nx,(row+2)*nx-1)
        try:diameter=acquisition_patch_diameter(list(ids),vertices,{'max_assisted_nodes':4})
        except ValueError:continue
        candidates.append((abs(row+.5-(ny-1)/2),diameter,ids))
    return [item[2] for item in sorted(candidates)]

def probe_route_pose(planner,rec,q,position,rotation,vertex_index):
    # The same coordinates enter two JSON boundaries: planner IPC and events.
    position=np.asarray(position,dtype=float).tolist()
    result=planner.call(dict(q=np.asarray(q,dtype=float).tolist(),tcp_world=position,
                            quaternion_wxyz=rotation.as_quat()[[3,0,1,2]].tolist()))
    rec.mark('corner_approach_probe',vertex_index=int(vertex_index),goal=position,planner_id=planner.count,
             success=bool(result.get('success')),status=result.get('status'),purpose='folded_transfer_route')
    return result

def execute(robot,rec,planner):
    from safety import Halted
    c=Controller(robot,rec,planner);c.fold()
    if not fold_satisfactory(measure(c.scene.cloth_vertices(),c.scene.topology,c.cfg)):
        raise Halted('Folding on A has not reached paired-corner and overlap targets; transfer was not started')
    nx,ny=c.scene.topology['physical_grid'];v=c.scene.cloth_vertices()
    patch=c.cfg['task_spec'].get('transfer_grasp_mode')=='adjacent_paired_patch'
    candidates=(transfer_patch_candidates if patch else transfer_grasp_candidates)(v,c.scene.topology)
    if not candidates:raise Halted('No aligned local patch for the configured transfer grasp mode')
    desired=folded_destination(c.scene.topology,c.cfg['task_spec'])
    delta=c.cfg['task_spec']['initial_parameters']['destination_yaw_deg']-c.cfg['task_spec']['initial_parameters']['yaw_deg']
    destination_rotation=Rotation.from_euler('z',delta,degrees=True)*c.rotation
    height=1.18;pair=None
    # Check the candidate local pinches through the actual transfer heights and
    # wrist rotation before acquiring either. Probes are saved but never executed.
    for candidate in candidates:
        point=v[list(candidate)].mean(0);target=desired[list(candidate)].mean(0).tolist()
        q=robot.state()[0]['joints'];reachable=True
        waypoints=[([*point[:2],.94],c.rotation),([*point[:2],c.cfg['table_height']+.018],c.rotation),
                   ([*point[:2],height],c.rotation),([.12,.06,height],c.rotation),
                   ([*target,height],destination_rotation),([*target,.88],destination_rotation),
                   ([*target,c.place_height],destination_rotation)]
        for position,rotation in waypoints:
            result=probe_route_pose(planner,rec,q,position,rotation,candidate[0])
            if not result.get('success'):reachable=False;break
            q=result['q'][-1]
        if reachable:pair=candidate;break
    if pair is None:raise Halted('No local paired-layer grasp has a collision-checked transfer route')
    c.rec.mark('transfer_grasp_selected',vertex_ids=list(pair),
               selection='adjacent_paired_patch' if patch else 'middle_open_edge_first',
               material_rows=sorted({int(i//nx) for i in pair}),
               initial_pair_distance_m=float(np.linalg.norm(v[pair[0]]-v[pair[1]])),
               initial_patch_diameter_m=acquisition_patch_diameter(list(pair),v,c.cfg['task_spec']),
               grasp_centroid_world_m=v[list(pair)].mean(0).tolist())
    if patch:c.acquire(patch_indices=pair,kind='paired_layer_patch')
    else:c.acquire(pair[0],pair[1],kind='paired_layers')
    c.mark('layers_acquired',vertex_ids=list(pair))
    c.rec.phase='transfer';p=c.tcp()
    c.move([p[0],p[1],height]);c.move([.12,.06,height])
    target=desired[list(pair)].mean(0).tolist()
    # Both layers travel together at one local pinch. Wrist yaw aligns the fold
    # with the destination while cloth shape remains entirely solver-controlled.
    c.rotation=destination_rotation
    c.move([*target,height]);c.mark('transfer_complete')
    c.rec.phase='lay_down'
    v=c.scene.cloth_vertices();low=int(np.argmin(v[:,2]));p=c.tcp()
    c.move([*(p[:2]+desired[low]-v[low,:2]),p[2]])
    v=c.scene.cloth_vertices();p=c.tcp()
    drop=max(0.,float(v[:,2].min()-c.cfg['table_height']-.008))
    c.move([p[0],p[1],p[2]-drop]);start=c.tcp()
    c.mark('fold_trailing_edge_positioned',material_vertex=low,target_xy=desired[low].tolist())
    end=np.r_[target,c.place_height]
    for fraction in [.25,.5,.75,1.]:c.move(start+(end-start)*fraction)
    c.release();c.mark('placed_on_B');c.finish()
