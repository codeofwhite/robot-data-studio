"""Layer and material-orientation checks from saved FEM vertices, never event claims."""
import numpy as np
from folding_v3.garment_assets import signed_capped_volume

def projected_masks(vertices, face_groups, resolution=112):
    v=np.asarray(vertices,float)[:,:2];low=v.min(0)-.002;high=v.max(0)+.002
    pitch=(high-low)/resolution;masks=[]
    for faces in face_groups:
        mask=np.zeros((resolution,resolution),bool)
        for ids in faces:
            tri=v[ids];a,b,c=tri
            det=(b-a)[0]*(c-a)[1]-(b-a)[1]*(c-a)[0]
            if abs(det)<1e-12:continue
            lo=np.maximum(0,np.floor((tri.min(0)-low)/pitch-.5).astype(int))
            hi=np.minimum(resolution-1,np.ceil((tri.max(0)-low)/pitch-.5).astype(int))
            if (lo>hi).any():continue
            x=low[0]+(np.arange(lo[0],hi[0]+1)+.5)*pitch[0]
            y=low[1]+(np.arange(lo[1],hi[1]+1)+.5)*pitch[1]
            xx,yy=np.meshgrid(x,y);p=np.stack((xx,yy),-1)-a
            u=(p[...,0]*(c-a)[1]-p[...,1]*(c-a)[0])/det
            w=((b-a)[0]*p[...,1]-(b-a)[1]*p[...,0])/det
            mask[lo[1]:hi[1]+1,lo[0]:hi[0]+1]|=(u>=-1e-9)&(w>=-1e-9)&(u+w<=1+1e-9)
        masks.append(mask)
    return masks,float(np.prod(pitch))

def garment_measure(v,topology):
    from scipy.spatial import cKDTree
    g=topology['garment'];faces=np.asarray(topology['faces']);rest=np.asarray(topology['rest_vertices'])
    tri=v[faces];normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);centroids=tri.mean(1)
    front=np.asarray(g['front_faces']);back=np.asarray(g['back_faces'])
    front_z=float(normals[front,2].sum()/max(np.linalg.norm(normals[front],axis=1).sum(),1e-12))
    # Opposing material faces are selected in reference coordinates, not reselected
    # from the deformed state. This score is invariant under rigid-body turnover.
    rtri=rest[faces];rn=np.cross(rtri[:,1]-rtri[:,0],rtri[:,2]-rtri[:,0]);rc=rtri.mean(1)
    matches={}
    for left,right in [(front,back),(back,front)]:
        distance,near=cKDTree(rc[right,:2]).query(rc[left,:2])
        for a,b,d in zip(left,right[near],distance):
            if d<.018:matches[int(a)]=int(b)
    panel_scores={};front_panel_z={}
    for name,indices in g['panels'].items():
        front_ids=np.intersect1d(front,np.asarray(indices,dtype=int))
        front_panel_z[name]=float(normals[front_ids,2].sum()/max(np.linalg.norm(normals[front_ids],axis=1).sum(),1e-12))
        ids=np.array([i for i in indices if i in matches],int)
        partner=np.array([matches[int(i)] for i in ids],int)
        reference=np.einsum('ij,ij->i',rn[ids],rc[ids]-rc[partner])
        current=np.einsum('ij,ij->i',normals[ids],centroids[ids]-centroids[partner])
        valid=(abs(reference)>1e-12)&(np.linalg.norm(centroids[ids]-centroids[partner],axis=1)>.0001)
        panel_scores[name]=float(((current*reference>0)&valid).mean()) if len(ids) else 0.
    volume=signed_capped_volume(v,faces,list(g['openings'].values()))
    return dict(front_normal_z=front_z,front_panel_normal_z=front_panel_z,capped_volume_m3=volume,
        orientation_volume_ratio=volume/g['reference_capped_volume_m3'],outward_panel_fraction=panel_scores)

def measure(vertices,topology,cfg):
    v=np.asarray(vertices,float);spec=cfg['task_spec'];faces=np.asarray(topology['faces'])
    low,high=np.asarray(spec['target_region_xy_m']);inside=((v[:,:2]>=low)&(v[:,:2]<=high)).all(1)
    height=v[:,2]-cfg['table_height']
    all_masks,cell=projected_masks(v,[faces])
    out=dict(target_surface_fraction=float((inside&(height>=-.001)&(height<=.04)).mean()),
        height_p95_m=float(np.percentile(height,95)),center_world_m=v.mean(0).tolist(),
        projected_area_fraction=float(all_masks[0].sum()*cell/topology['flat_area_m2']))
    if 'garment' in topology:
        out.update(garment_measure(v,topology));return out
    nx,ny=topology['physical_grid'];cols=np.arange(len(v))%nx
    left=faces[(cols[faces]<=nx//2).all(1)];right=faces[(cols[faces]>=nx//2).all(1)]
    masks,cell=projected_masks(v,[left,right]);union=(masks[0]|masks[1]).sum()
    pairs=[(i,i+nx-1-2*(i%nx)) for i in range(nx*ny) if i%nx<nx//2]
    pairs=np.asarray(pairs);delta=v[pairs[:,0]]-v[pairs[:,1]]
    corners=[(0,nx-1),((ny-1)*nx,nx*ny-1)]
    out.update(layer_overlap_iou=float((masks[0]&masks[1]).sum()/max(union,1)),
        layer_pair_xy_p90_m=float(np.percentile(np.linalg.norm(delta[:,:2],axis=1),90)),
        paired_corner_errors_m=[float(np.linalg.norm(v[a,:2]-v[b,:2])) for a,b in corners],
        full_width_m=float(np.mean(np.linalg.norm(v.reshape(ny,nx,3)[:,0,:2]-v.reshape(ny,nx,3)[:,-1,:2],axis=1))))
    if spec['id']=='folded_transfer':
        targets=spec['target_corners_xy_m']
        a,b,c=(np.asarray(targets[str(i)]) for i in [0,nx-1,(ny-1)*nx])
        expected=(a+c)/2+(b-a)/4
        out.update(target_fold_center_xy_m=expected.tolist(),
                   target_placement_center_error_m=float(np.linalg.norm(v[:,:2].mean(0)-expected)))
    return out

def fold_satisfactory(m):
    # A second fold or crumpled stack can align both material halves while
    # destroying the requested half-sized footprint. Require at least 80% of
    # the ideal single-fold area as well as correspondence and table support.
    return .40<=m['projected_area_fraction']<=.60 and m['layer_overlap_iou']>=.68 and max(m['paired_corner_errors_m'])<=.05 and m['layer_pair_xy_p90_m']<=.055 and m['height_p95_m']<=.04

def satisfactory(m,task):
    if m['target_surface_fraction']<.90:return False
    if task=='unfold_half':return m['projected_area_fraction']>=.85 and m['full_width_m']>=.34
    if task=='towel_half_fold':return fold_satisfactory(m)
    if task=='folded_transfer':return fold_satisfactory(m) and m['target_placement_center_error_m']<=.08
    if task=='garment_flip':return m['front_normal_z']<=-.45 and all(x<=-.35 for x in m['front_panel_normal_z'].values()) and m['projected_area_fraction']>=.28 and m['height_p95_m']<=.06
    return all(x>=.8 for x in m['outward_panel_fraction'].values()) and m['orientation_volume_ratio']>.1 and m['projected_area_fraction']>=.25

def task_result(data,events,topology,cfg):
    names=[e['name'] for e in events];required=cfg['task_spec']['required_stages'];task=cfg['task_id']
    start=next((e['tick'] for e in events if e['name']=='task_start'),int(data['tick'][0]))
    initial_ix=int(np.flatnonzero(data['tick']==start)[0])
    initial=measure(data['cloth_vertices'][initial_ix],topology,cfg);final=measure(data['cloth_vertices'][-1],topology,cfg)
    complete=all(n in names for n in required)
    if task=='unfold_half':valid=initial['layer_overlap_iou']>.6 and initial['full_width_m']<.08
    elif task in ('towel_half_fold','folded_transfer'):valid=initial['projected_area_fraction']>.9 and initial['full_width_m']>.36
    elif task=='garment_flip':valid=initial['front_normal_z']>.35
    else:valid=initial['orientation_volume_ratio']<-.1 and max(initial['outward_panel_fraction'].values())<.35
    hold=next((e['tick'] for e in events if e['name']=='terminal_hold'),None)
    final_tick=int(data['tick'][-1]);indices=np.flatnonzero(data['tick']>=final_tick-round(1/cfg['dt']))
    stable_goal=all(satisfactory(measure(data['cloth_vertices'][i],topology,cfg),task) for i in indices[::max(1,len(indices)//5)])
    pulls={e.get('vertex_index') for e in events if e['name']=='corner_adjusted'}
    gates=dict(task_initial_condition=bool(valid),task_stages_complete=complete,
        task_stages_in_order=complete and [names.index(n) for n in required]==sorted(names.index(n) for n in required),
        action_executed='contact_grasp_verified' in names,task_goal_reached=bool(satisfactory(final,task)),
        released_goal_persists=bool(hold is not None and final_tick-hold>=round(1/cfg['dt']) and stable_goal))
    if task in ('towel_half_fold','folded_transfer'):gates['both_corners_adjusted']=len(pulls)>=2
    if task=='folded_transfer':
        fold=next((e for e in events if e['name']=='fold_complete'),None)
        before=measure(data['cloth_vertices'][int(np.flatnonzero(data['tick']==fold['tick'])[0])],topology,cfg) if fold else None
        source=next(t for t in cfg['tables'] if t['id']=='A');lo=np.asarray(source['position'])-source['half_extents'];hi=np.asarray(source['position'])+source['half_extents']
        folded_v=data['cloth_vertices'][int(np.flatnonzero(data['tick']==fold['tick'])[0])] if fold else np.empty((0,3))
        source_fraction=float(((folded_v[:,:2]>=lo[:2])&(folded_v[:,:2]<=hi[:2])).all(1).mean()) if len(folded_v) else 0.
        gates['folded_on_A']=bool(before and fold_satisfactory(before) and source_fraction>=.95)
        transfer=next((e for e in events if e['name']=='transfer_complete'),None)
        moving=data['cloth_vertices'][(data['tick']>=fold['tick'])&(data['tick']<=transfer['tick'])] if fold and transfer else []
        errors=[]
        if len(moving):
            nx,ny=topology['physical_grid']
            errors=[float(np.linalg.norm(moving[:,a]-moving[:,b],axis=1).max())
                    for a,b in [(0,nx-1),((ny-1)*nx,nx*ny-1)]]
        gates['fold_retained_during_transfer']=bool(errors) and max(errors)<=.075
    return dict(initial=initial,final=final,distinct_adjusted_corners=len(pulls),
        assessment_scope='Task-specific physical-state diagnostics plus separate saved-frame inspection'),gates
