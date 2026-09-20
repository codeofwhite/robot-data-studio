"""Prepare independently versioned physical scenes; static USD assets stay frozen."""
import sys,json,hashlib,shutil
from pathlib import Path
import re
import numpy as np
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]
ASSETS=PROJECT/'assets/sources/robot-cloth-scenes-v1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def verify_scene_sources(binding):
    """Reject changed source dependencies before planning, replay or publication."""
    root=Path(binding['snapshot_root'])
    for rel,digest in binding['source_sha256'].items():
        if sha(root/rel)!=digest:raise ValueError('Scene dependency changed: '+rel)
    for name,mesh in binding.get('collision_meshes',{}).items():
        if sha(mesh['path'])!=mesh['sha256']:raise ValueError('Scene collision mesh changed: '+name)
        if 'physics_mjcf' in mesh:
            if sha(mesh['physics_mjcf'])!=mesh['physics_mjcf_sha256']:raise ValueError('Scene collision assembly changed')
            for path,digest in mesh['part_sha256'].items():
                if sha(path)!=digest:raise ValueError('Scene collision component changed: '+path)
    if 'topology_path' in binding and sha(binding['topology_path'])!=binding['topology_sha256']:raise ValueError('Scene cloth mapping changed')
    return True

def triangle_mesh(prim,cache):
    """Bake a USD solid into world-space triangles, including reflected transforms."""
    from pxr import UsdGeom
    import trimesh
    if prim.IsA(UsdGeom.Mesh):
        m=UsdGeom.Mesh(prim);v=np.asarray(m.GetPointsAttr().Get(),float);f=[];offset=0
        ids=np.asarray(m.GetFaceVertexIndicesAttr().Get(),int)
        for count in m.GetFaceVertexCountsAttr().Get():
            face=ids[offset:offset+count];offset+=count
            f.extend([[face[0],face[i],face[i+1]] for i in range(1,count-1)])
        f=np.asarray(f,int)
        if m.GetOrientationAttr().Get()=='leftHanded':f=f[:,::-1]
    elif prim.IsA(UsdGeom.Cube):
        mesh=trimesh.creation.box(extents=[UsdGeom.Cube(prim).GetSizeAttr().Get()]*3);v,f=mesh.vertices,mesh.faces
    elif prim.IsA(UsdGeom.Cylinder):
        c=UsdGeom.Cylinder(prim);mesh=trimesh.creation.cylinder(radius=c.GetRadiusAttr().Get(),height=c.GetHeightAttr().Get(),sections=24)
        v,f=np.asarray(mesh.vertices).copy(),mesh.faces
        if c.GetAxisAttr().Get()=='X':v=v[:,[2,0,1]]
        elif c.GetAxisAttr().Get()=='Y':v=v[:,[1,2,0]]
    else:raise ValueError('Unsupported collision geometry: '+str(prim.GetPath())+' '+prim.GetTypeName())
    mat=np.asarray(cache.GetLocalToWorldTransform(prim)).T
    v=(mat[:3,:3]@v.T).T+mat[:3,3]
    if np.linalg.det(mat[:3,:3])<0:f=f[:,::-1]
    if not np.isfinite(v).all() or len(f)==0:raise ValueError('Invalid solid: '+str(prim.GetPath()))
    return v,np.asarray(f,int)

def write_obj(path,parts):
    vertices=[];faces=[];offset=0
    for v,f in parts:vertices.extend(v);faces.extend(f+offset);offset+=len(v)
    Path(path).write_text('\n'.join(['v %.12g %.12g %.12g'%tuple(v) for v in vertices]+['f %d %d %d'%tuple(f+1) for f in faces])+'\n')
    return {'vertices':len(vertices),'triangles':len(faces),'sha256':sha(path)}

def collision_solid(prim,cache):
    """Weld redundant CAD vertices; tightly bound nonmanifold convex CAD parts only."""
    import trimesh
    v,f=triangle_mesh(prim,cache);mesh=trimesh.Trimesh(np.round(v,6),f,process=True)
    mesh.merge_vertices(digits_vertex=6)
    report={'weld_precision_m':1e-6,'max_vertex_quantization_m':float(np.linalg.norm(np.round(v,6)-v,axis=1).max()),'source_triangles':len(f),'method':'vertex_weld'}
    if not mesh.is_watertight:
        hull=mesh.convex_hull
        # A general concave mesh may NOT silently become a convex collider.
        # Millimetre local coordinates avoid closest-point cancellation on micron CAD facets.
        centre=v.mean(axis=0);metric_hull=hull.copy();metric_hull.vertices=(metric_hull.vertices-centre)*1000
        _,distance,_=trimesh.proximity.closest_point(metric_hull,(v-centre)*1000)
        error=float(distance.max())/1000
        if error>5e-5:raise ValueError('Open or nonmanifold solid needs an explicit collision model: '+str(prim.GetPath())+' max convex surface error '+str(error))
        mesh=hull;report.update(method='convex_CAD_topology_repair',max_source_surface_distance_m=error)
    if not mesh.is_watertight:raise ValueError('Collision repair did not produce a closed solid: '+str(prim.GetPath()))
    if not mesh.is_winding_consistent:raise ValueError('Inconsistent solid winding: '+str(prim.GetPath()))
    if mesh.volume<0:mesh.invert()
    return np.asarray(mesh.vertices),np.asarray(mesh.faces),report

def cloth_mapping(stage,entry,stride=4):
    """Preserve material coordinates and map the original visual mesh to FEM nodes."""
    if 'topology_asset' in entry:
        from folding_v3.garment_assets import load_mapping
        return load_mapping(stage,entry)
    from pxr import UsdGeom
    prim=stage.GetPrimAtPath(entry['prim']);mesh=UsdGeom.Mesh(prim)
    v=np.asarray(mesh.GetPointsAttr().Get(),float)
    mat=np.asarray(UsdGeom.XformCache().GetLocalToWorldTransform(prim)).T
    v=(mat[:3,:3]@v.T).T+mat[:3,3]
    st=np.asarray(UsdGeom.PrimvarsAPI(mesh).GetPrimvar('st').Get(),float)
    us=np.unique(st[:,0]);vs=np.unique(st[:,1]);nx,ny=len(us),len(vs)
    if nx*ny!=len(v) or not np.allclose(st.reshape(ny,nx,2)[...,0],us):raise ValueError('Unsupported cloth material grid')
    xs=np.unique(np.r_[np.arange(0,nx,stride),nx-1]);ys=np.unique(np.r_[np.arange(0,ny,stride),ny-1])
    selected=(ys[:,None]*nx+xs[None,:]).ravel();initial=v[selected]
    w,h=entry['size_m'];u=(st[:,0]-us[0])/(us[-1]-us[0]);vv=(st[:,1]-vs[0])/(vs[-1]-vs[0])
    rest=np.column_stack((u[selected]*w,vv[selected]*h,np.zeros(len(selected))))
    # Rest coordinates are material coordinates; current coordinates remain world-space.
    rest[:,:2]+=initial[:,:2].mean(axis=0)-rest[:,:2].mean(axis=0);rest[:,2]=float(initial[:,2].max())
    faces=[];sx=len(xs)
    for j in range(len(ys)-1):
        for i in range(sx-1):
            a=j*sx+i;faces.extend([[a,a+1,a+sx+1],[a,a+sx+1,a+sx]])
    f=np.asarray(faces,int);edges=np.asarray(sorted({tuple(sorted((int(a),int(b)))) for t in f for a,b in zip(t,np.roll(t,-1))}))
    # Piecewise triangular barycentric coordinates use exactly the physical triangulation.
    mapping=[];weights=[]
    for row in range(ny):
        j=min(np.searchsorted(ys,row,side='right')-1,len(ys)-2);y=(row-ys[j])/(ys[j+1]-ys[j])
        for col in range(nx):
            i=min(np.searchsorted(xs,col,side='right')-1,len(xs)-2);x=(col-xs[i])/(xs[i+1]-xs[i]);a=j*sx+i
            if x>=y:mapping.append([a,a+1,a+sx+1]);weights.append([1-x,x-y,y])
            else:mapping.append([a,a+sx+1,a+sx]);weights.append([1-y,x,y-x])
    ratio=np.linalg.norm(initial[edges[:,0]]-initial[edges[:,1]],axis=1)/np.linalg.norm(rest[edges[:,0]]-rest[edges[:,1]],axis=1)
    return {'rest_vertices':rest.tolist(),'initial_vertices':initial.tolist(),'faces':f.tolist(),'edges':edges.tolist(),
        'flat_area_m2':w*h,'rest_shape':'flat material coordinates from source USD UV grid','initial_max_edge_ratio':float(ratio.max()),
        'source_prim':entry['prim'],'source_vertex_ids':selected.tolist(),'source_vertex_count':len(v),'visual_indices':np.asarray(mapping,int).tolist(),'visual_weights':np.asarray(weights,float).tolist(),
        'visual_uv':st.tolist(),'material_size_m':[w,h],'physical_grid':[len(xs),len(ys)]}

def bind_scene(out,cfg,scene_name,active_robot='FrankaLeft'):
    """Compile one frozen Studio scene for physics AND planning, without rebuilding its layout."""
    from pxr import Usd,UsdGeom,UsdPhysics,UsdUtils
    from scipy.spatial.transform import Rotation
    if not re.fullmatch('[a-z][a-z0-9_]+',scene_name):raise ValueError('Invalid scene name')
    out=Path(out);records={};registered={}
    for prefix in ['SCN','MDL']:
        ident=prefix+'-rcloth-'+scene_name.replace('_','-')
        record=json.loads((PROJECT/'assets/registry'/ident/'v000001.json').read_text())
        for a in record['artifacts']:
            if sha(ASSETS/a['path'])!=a['sha256']:raise ValueError('Registered source changed: '+a['path'])
        records[prefix]={'asset_id':ident,'version':1,'content_sha256':record['content_sha256']}
        registered[prefix]=record
    entrypoint=(ASSETS/registered['MDL']['data']['entrypoint']).resolve()
    if not entrypoint.is_relative_to(ASSETS.resolve()) or entrypoint.name!='scene.usda':raise ValueError('Invalid registered scene entrypoint')
    source=entrypoint.parent
    manifest=json.loads((source/'manifest.json').read_text())
    if manifest['id']!=scene_name:raise ValueError('Scene manifest identity mismatch')
    stage=Usd.Stage.Open(str(entrypoint));cache=UsdGeom.XformCache()
    if UsdGeom.GetStageMetersPerUnit(stage)!=1 or UsdGeom.GetStageUpAxis(stage)!='Z':raise ValueError('Only metre Z-up scenes supported')
    layers,files,unresolved=UsdUtils.ComputeAllDependencies(str(source/'scene.usda'))
    if set(unresolved)-{'OmniPBR.mdl'}:raise ValueError('Unresolved scene dependencies: '+str(unresolved))
    snapshot=out/'scene_source';snapshot.mkdir(exist_ok=False)
    deps={Path(l.realPath) for l in layers}|{Path(p) for p in files}|{source/'manifest.json',ASSETS/'build_scenes.py'}
    for rel in manifest.get('source_files',[]):
        extra=(ASSETS/rel).resolve()
        if not extra.is_relative_to(ASSETS.resolve()):raise ValueError('Scene builder dependency leaves asset root')
        deps.add(extra)
    hashes={}
    for p in sorted(deps):
        rel=p.relative_to(ASSETS);dest=snapshot/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest);hashes[str(rel)]=sha(p)
    robots={r['name']:r for r in manifest['robot_poses']}
    binding={'schema_version':1,'scene':records['SCN'],'model':records['MDL'],'scene_name':scene_name,
        'snapshot_root':str(snapshot),'usd_relative_path':str((source/'scene.usda').relative_to(ASSETS)),
        'source_sha256':hashes,'renderer_builtin_dependencies':unresolved,'active_robot':active_robot,
        'passive_robots':[n for n in robots if n!=active_robot],
        'control_scope':'one articulated Franka; other source robots retain authored poses as fixed collision obstacles',
        'full_scene_task_verified':False}
    (out/'scene_binding.json').write_text(json.dumps(binding,indent=2))
    if active_robot not in robots or not robots[active_robot]['source'].startswith('robots/franka/'):
        binding['status']='blocked';binding['reason']='No verified controller for the requested source robot; no substitute robot inserted.'
        (out/'scene_binding.json').write_text(json.dumps(binding,indent=2))
        raise ValueError(binding['reason'])
    if not manifest['cloth']:raise ValueError('This executor requires a source cloth mesh')
    entry=manifest['cloth'][0];topology=cloth_mapping(stage,entry)
    dynamic=entry['prim'];prefix=re.sub(r'\d+$','',dynamic)
    excluded=[];environment=[];table_parts=[];solids=[];top=None;tables=[]
    for p in stage.GetPrimAtPath('/World').GetChildren():
        path=str(p.GetPath());name=p.GetName()
        if name in robots or name=='Materials' or p.IsA(UsdGeom.Camera) or 'Light' in p.GetTypeName():continue
        if path==dynamic or re.sub(r'\d+$','',path)==prefix+'Backing':
            excluded.append({'prim':path,'reason':'dynamic cloth visual surface'});continue
        if p.IsA(UsdGeom.BasisCurves):
            excluded.append({'prim':path,'reason':'visual stitch or decorative curve, no rigid collision'});continue
        if name.startswith(('FloorJoint','CuttingGrid','MaterialSwatch','LabSign')):
            excluded.append({'prim':path,'reason':'surface decoration or non-task material sample'});continue
        if not p.IsA(UsdGeom.Gprim):continue
        if UsdGeom.Imageable(p).ComputeVisibility()=='invisible':continue
        v,f,repair=collision_solid(p,cache)
        group='table' if name.startswith('Worktop') else 'environment'
        (table_parts if group=='table' else environment).append((v,f))
        solids.append({'prim':path,'group':group,'triangles':len(f),'topology_processing':repair,'min':v.min(axis=0).tolist(),'max':v.max(axis=0).tolist()})
        if group=='table':
            lo,hi=v.min(axis=0),v.max(axis=0)
            if top is not None and abs(top-float(hi[2]))>1e-6:raise ValueError('Task requires same-height tabletops')
            top=float(hi[2]);table={'position':((lo+hi)/2).tolist(),'half_extents':((hi-lo)/2).tolist()}
            declared=next((t for t in manifest.get('table_regions',[]) if t['prim']==path),None)
            if declared:
                if not np.allclose(table['position'],declared['position'],atol=1e-6) or not np.allclose(table['half_extents'],declared['half_extents'],atol=1e-6):raise ValueError('Task tabletop metadata differs from USD geometry')
                table['id']=declared['id']
            tables.append(table)
    for name in binding['passive_robots']:
        found=0
        for p in Usd.PrimRange(stage.GetPrimAtPath('/World/'+name),Usd.TraverseInstanceProxies()):
            if p.HasAPI(UsdPhysics.CollisionAPI) and UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get():
                v,f,repair=collision_solid(p,cache);environment.append((v,f));found+=1
                solids.append({'prim':str(p.GetPath()),'group':'environment','role':'fixed_passive_robot','triangles':len(f),'topology_processing':repair,'min':v.min(axis=0).tolist(),'max':v.max(axis=0).tolist()})
        if not found:raise ValueError('Passive robot has no imported collision geometry: '+name)
    if top is None:raise ValueError('No source worktop')
    cfg['table']={k:v for k,v in tables[0].items() if k!='id'}
    if len(tables)>1:
        if len(tables)!=len(manifest.get('table_regions',[])):raise ValueError('Multiple worktops require explicit table_regions metadata')
        cfg['tables']=tables
    if 'task_spec' in manifest:cfg['task_spec']=manifest['task_spec']
    meshdir=out/'scene_geometry';meshdir.mkdir(exist_ok=False)
    collision={}
    for name,parts in [('table',table_parts),('environment',environment)]:
        dest=meshdir/(name+'.obj');collision[name]={'path':str(dest),**write_obj(dest,parts)}
    # Keep closed CAD components separate in the physics importer. Welding the entire
    # room into one mesh joins touching cabinets/fixtures and creates nonmanifold edges.
    import xml.etree.ElementTree as ET
    xml=ET.Element('mujoco',model='source_scene_fixed_environment');ET.SubElement(xml,'compiler',angle='radian',meshdir='parts')
    asset=ET.SubElement(xml,'asset');world=ET.SubElement(xml,'worldbody');body=ET.SubElement(world,'body',name='source_environment')
    partdir=meshdir/'parts';partdir.mkdir();part_hashes={}
    for i,part in enumerate(environment):
        name=f'part_{i:04d}';dest=partdir/(name+'.obj');write_obj(dest,[part]);part_hashes[str(dest)]=sha(dest)
        ET.SubElement(asset,'mesh',name=name,file=dest.name)
        ET.SubElement(body,'geom',name=name,type='mesh',mesh=name,friction='.6 .005 .0001')
    mjcf=meshdir/'environment.xml';ET.ElementTree(xml).write(mjcf,encoding='unicode')
    collision['environment'].update(physics_mjcf=str(mjcf),physics_mjcf_sha256=sha(mjcf),part_sha256=part_hashes)
    if len(table_parts)>1:
        xml=ET.Element('mujoco',model='source_scene_table_slabs');ET.SubElement(xml,'compiler',angle='radian',meshdir='table_parts')
        asset=ET.SubElement(xml,'asset');world=ET.SubElement(xml,'worldbody');body=ET.SubElement(world,'body',name='source_table')
        tabledir=meshdir/'table_parts';tabledir.mkdir();table_hashes={}
        for i,part in enumerate(table_parts):
            name=f'slab_{i:02d}';dest=tabledir/(name+'.obj');write_obj(dest,[part]);table_hashes[str(dest)]=sha(dest)
            ET.SubElement(asset,'mesh',name=name,file=dest.name);ET.SubElement(body,'geom',name=name,type='mesh',mesh=name,friction='.6 .005 .0001')
        mjcf=meshdir/'table.xml';ET.ElementTree(xml).write(mjcf,encoding='unicode')
        collision['table'].update(physics_mjcf=str(mjcf),physics_mjcf_sha256=sha(mjcf),part_sha256=table_hashes)
    topology_path=meshdir/'cloth_topology.json';topology_path.write_text(json.dumps(topology,indent=2))
    prim=stage.GetPrimAtPath('/World/'+active_robot);mat=np.asarray(cache.GetLocalToWorldTransform(prim)).T
    yaw=float(Rotation.from_matrix(mat[:3,:3]).as_euler('xyz',degrees=True)[2]);base=mat[:3,3]
    qs={x['name']:np.deg2rad(x['angle_deg']) for x in robots[active_robot]['joints']}
    cfg['home']=[float(qs['panda_joint'+str(i)]) for i in range(1,8)]+[.025,.025]
    cfg['bases']=[base.tolist()];cfg['yaws']=[yaw];cfg['table_height']=top
    cfg['nominal_mass_kg']=topology['flat_area_m2']*cfg['material_provenance']['gsm']/1000
    cfg['workspace_low']=[-.85,-.85,top-.3];cfg['workspace_high']=[.85,.5,1.65]
    if 'task_spec' in cfg:
        cfg['workspace_low']=cfg['task_spec']['workspace_low'];cfg['workspace_high']=cfg['task_spec']['workspace_high']
    for name,source_camera in [('front','hero'),('top','overhead')]:
        camera=next((p for p in stage.Traverse() if p.IsA(UsdGeom.Camera) and source_camera.lower() in p.GetName().lower()),None)
        if camera is None:raise ValueError('Missing original camera '+source_camera)
        m=np.asarray(cache.GetLocalToWorldTransform(camera)).T;c=UsdGeom.Camera(camera)
        cfg['camera'][name]={'pos':m[:3,3].tolist(),'lookat':(m[:3,3]-m[:3,2]).tolist(),'up':m[:3,1].tolist(),
            'fov':float(np.rad2deg(2*np.arctan(float(c.GetHorizontalApertureAttr().Get())/(2*float(c.GetFocalLengthAttr().Get())))))}
    binding.update(status='compiled',collision_meshes=collision,collision_prims=solids,excluded_prims=excluded,
        dynamic_cloth=entry,topology_path=str(topology_path),topology_sha256=sha(topology_path),
        table_height_m=top,active_robot_base=base.tolist(),active_robot_yaw_deg=yaw,
        initial_cloth_edge_ratio=topology['initial_max_edge_ratio'],
        collision_policy='source world-space triangles; table separate; all remaining fixed solids and passive robot colliders share one static IPC body')
    if len(tables)>1:binding['table_regions']=tables
    cfg['scene_binding']=binding
    (out/'scene_binding.json').write_text(json.dumps(binding,indent=2))
    return binding

def prepare(out,cfg):
    out=Path(out);work=out/'physical_scene';(work/'assets').mkdir(parents=True,exist_ok=False)
    (work/'config.json').write_text(json.dumps(cfg,indent=2))
    sys.path.insert(0,str(ROOT/'runtime'))
    import prepare_assets,scene
    prepare_assets.ROOT=work;scene.ROOT=work
    prepare_assets.prepare()
    if 'scene_binding' in cfg:
        binding=cfg['scene_binding'];verify_scene_sources(binding)
        topology=json.loads(Path(binding['topology_path']).read_text())
        write_obj(work/'assets/square.obj',[(np.asarray(topology['rest_vertices']),np.asarray(topology['faces']))])
        (work/'assets/cloth_topology.json').write_text(json.dumps(topology,indent=2))
    files=list(ROOT.glob('*.py'))+list(ROOT.glob('*.json'))+list((ROOT/'runtime').glob('*.py'))
    if cfg.get('task_spec',{}).get('batch_id')=='tabletop_v2':
        files += [p for p in (ROOT/'tabletop_v2').rglob('*') if p.suffix in {'.py','.json'} and p.is_file()]
    if cfg.get('task_spec',{}).get('batch_id')=='folding_v3':
        files += [p for p in (ROOT/'folding_v3').rglob('*') if p.suffix in {'.py','.json'} and p.is_file()]
    if cfg.get('task_spec',{}).get('batch_id')=='fixtures_v4':
        files += [p for p in (ROOT/'fixtures_v4').rglob('*') if p.suffix in {'.py','.json'} and p.is_file()]
    manifest={'code':{str(p.relative_to(ROOT)):sha(p) for p in files},
              'physical_assets':{str(p.relative_to(work)):sha(p) for p in (work/'assets').rglob('*') if p.is_file()},
              'shared_assets':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'runtime/upstream_assets').rglob('*') if p.is_file()}}
    if 'scene_binding' in cfg:
        manifest['scene_binding']=cfg['scene_binding']
        manifest['scene_binding_sha256']=sha(out/'scene_binding.json')
    snapshot=out/'source_snapshot';snapshot.mkdir()
    for p in files:
        dest=snapshot/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    (out/'source_manifest.json').write_text(json.dumps(manifest,indent=2))
    return scene
