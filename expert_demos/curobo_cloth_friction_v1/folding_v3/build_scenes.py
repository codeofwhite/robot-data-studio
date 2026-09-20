"""Create independent registered scenes for the five approved second-batch tasks."""
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

HERE=Path(__file__).resolve().parent; CORE=HERE.parent; PROJECT=CORE.parents[1]
ASSETS=PROJECT/'assets/sources/robot-cloth-scenes-v1'
sys.path.insert(0,str(CORE))
from folding_v3 import TASKS, catalog

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def grid():
    return np.array([[u,v,0.] for v in np.linspace(-.15,.15,61) for u in np.linspace(-.2,.2,81)])

def transform(v, center, yaw, height=.784):
    return Rotation.from_euler('z',yaw,degrees=True).apply(v)+np.r_[center,height]

def rectangular_points(cfg):
    v=grid(); selected=v[:,0]>0; angle=np.deg2rad(cfg['initial_fold_deg'])
    v[selected,2]=v[selected,0]*np.sin(angle);v[selected,0]*=np.cos(angle)
    return transform(v,cfg['center'],cfg['yaw_deg'])

def task_spec(task,variant,topology=None):
    book=catalog();entry=book['tasks'][task];c=entry['variants'][variant]
    center=c.get('destination_center',c['center']);yaw=c.get('destination_yaw_deg',c['yaw_deg'])
    source=transform(grid(),c['center'],c['yaw_deg']);target=transform(grid(),center,yaw)
    corners=[0,80,60*81,61*81-1];physical=[0,20,315,335]
    spec=dict(id=task,batch_id='folding_v3',variant_id=variant,name=entry['name'],initial_parameters=c,
        source_table=c['source_table'],target_table=c['target_table'],target_center_world_m=center+[.78],
        target_region_xy_m=[[.11,-.69],[.69,.09]],source_center_world_m=c['center']+[.78],
        target_corners_xy_m={str(i):target[j,:2].tolist() for i,j in zip(physical,corners)},
        source_corners_xy_m={str(i):source[j,:2].tolist() for i,j in zip(physical,corners)},
        target_outline_xy_m=target[[0,80,4940,4860,0],:2].tolist(),
        primary_corner=20 if task!='folded_transfer' else 335,
        required_stages=entry['required_stages'],workspace_low=[-.8,-.98,.50],workspace_high=[.85,.85,1.65],
        grasp_mode='local_soft_position_constraint',assistance_strength=book['assisted_strength'],
        max_assisted_nodes=2 if task=='folded_transfer' else 1,
        material_preset='medium', material_display=c['material'],
        material_note='Synthetic cotton/terry appearance and medium FEM preset; not measured towel mechanics',
        acceptance='Visible task completion, measured layer/orientation diagnostics and explicit saved-frame review')
    if c.get('transfer_grasp_mode')=='adjacent_paired_patch':
        if task!='folded_transfer':raise ValueError('Four-node patch is approved only for folded transfer')
        spec.update(transfer_grasp_mode='adjacent_paired_patch',max_assisted_nodes=4,
                    max_grasp_patch_diameter_m=.04)
    if topology is not None:
        garment=topology['garment'];spec['garment']=garment
        spec['primary_corner']=garment['keypoints']['left_hem'] if task=='garment_flip' else garment['keypoints']['left_cuff_lower']
        xy=np.asarray(topology['initial_vertices'])[:,:2];lo=xy.min(0);hi=xy.max(0)
        spec['target_outline_xy_m']=[[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]],[lo[0],lo[1]]]
    return spec

def build(task,variant=None):
    from pxr import Usd,UsdGeom,UsdShade,UsdUtils,Sdf,Vt,Gf
    from scene_adapter import cloth_mapping
    sys.path[:0]=[str(PROJECT/'backend/src'),str(PROJECT/'packages/robot-data-contracts/src')]
    from robot_data_contracts.asset import AssetDraft
    from robot_data_studio.services.asset_service import AssetRegistry
    entry=catalog()['tasks'][task];variant=variant or entry.get('default_variant','v002')
    cfg=entry['variants'][variant]
    dest=ASSETS/'scenes/folding_v3'/task/variant
    if dest.exists():
        manifest=json.loads((dest/'manifest.json').read_text())
        if manifest['task_spec']['initial_parameters']!=cfg:raise ValueError('Use a new variant for a changed immutable scene')
        return dest
    topology=None
    if cfg['kind']=='garment':
        from folding_v3.garment_assets import prepare_garment
        points,faces,topology=prepare_garment(cfg)
    else:points=rectangular_points(cfg)
    spec=task_spec(task,variant,topology)
    dest.mkdir(parents=True)
    base=ASSETS/'scenes/l_table_transfer_mild'
    manifest=json.loads((base/'manifest.json').read_text())
    stage=Usd.Stage.CreateNew(str(dest/'scene.usda'))
    stage.GetRootLayer().subLayerPaths=[str(base/'scene.usda')]
    UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,'Z')
    cloth=UsdGeom.Mesh(stage.GetPrimAtPath(manifest['cloth'][0]['prim']))
    cloth.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points.astype(np.float32)))
    if topology is not None:
        cloth.GetFaceVertexCountsAttr().Set([3]*len(faces));cloth.GetFaceVertexIndicesAttr().Set(faces.ravel().tolist())
        uv=UsdGeom.PrimvarsAPI(cloth).GetPrimvar('st');uv.Set(Vt.Vec2fArray.FromNumpy(np.array(topology['visual_uv'],np.float32)));uv.SetInterpolation('vertex')
        cloth.CreateSubdivisionSchemeAttr('none')
        topology['source_prim']=str(cloth.GetPath())
        (dest/'cloth_topology.json').write_text(json.dumps(topology,indent=2))
        manifest['cloth'][0].update(topology_asset=str((dest/'cloth_topology.json').relative_to(ASSETS)),
            size_m=topology['material_size_m'],vertices=len(points))
        from folding_v3.garment_assets import SOURCE
        (dest/'source_garment.obj').write_bytes(SOURCE.read_bytes())
        (dest/'SOURCE_LICENSE.txt').write_bytes(Path('/data/zhanghejun/DiffCloth/LICENSE').read_bytes())
        (dest/'garment_assets.py').write_bytes((HERE/'garment_assets.py').read_bytes())
    for prim in stage.GetPrimAtPath('/World').GetChildren():
        name=prim.GetName()
        if name.startswith('SewnHem'):
            if topology is not None:UsdGeom.Imageable(prim).MakeInvisible()
            else:
                ids=list(range(81))+[j*81+80 for j in range(1,61)]+list(range(4939,4859,-1))+[j*81 for j in range(59,0,-1)]+[0]
                UsdGeom.BasisCurves(prim).GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points[ids].astype(np.float32)))
        if name.startswith('TaskClothBacking'):UsdGeom.Imageable(prim).MakeInvisible()
        if name.startswith('TargetOutline'):
            UsdGeom.BasisCurves(prim).GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(np.array([p+[.781] for p in spec['target_outline_xy_m']],np.float32)))
    # Distinct material panels make front/back turnover visible in both cameras.
    def material(name,color):
        m=UsdShade.Material.Define(stage,'/World/Materials/FoldingV3'+name)
        shader=UsdShade.Shader.Define(stage,str(m.GetPath())+'/Surface');shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.9)
        m.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
        return m
    if topology is not None:
        for name,ids,color in [('Front',topology['garment']['front_faces'],(.12,.42,.64)),('Back',topology['garment']['back_faces'],(.67,.31,.16))]:
            subset=UsdGeom.Subset.CreateGeomSubset(cloth,name,UsdGeom.Tokens.face,ids,'materialBind')
            UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(material(name,color))
    elif cfg['material']=='terry':
        # Reuse the already-present woven texture; no external downloads.
        candidates=[p for p in stage.Traverse() if p.IsA(UsdShade.Material) and 'terry' in p.GetName().lower()]
        if candidates:UsdShade.MaterialBindingAPI.Apply(cloth.GetPrim()).Bind(UsdShade.Material(candidates[0]))
        else:UsdShade.MaterialBindingAPI.Apply(cloth.GetPrim()).Bind(material('Towel',(.76,.55,.30)))
    stage.GetRootLayer().customLayerData=dict(studio_status='FOLDING_TASK_CANDIDATE',task_success='UNTESTED')
    stage.GetRootLayer().Save()
    scene_name='fv3_'+task+'_'+variant
    (dest/'builder.py').write_bytes(Path(__file__).read_bytes());(dest/'catalog.json').write_bytes((HERE/'catalog.json').read_bytes())
    (dest/'task_spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
    source_names=['builder.py','catalog.json','task_spec.json']
    if topology is not None:source_names+=['cloth_topology.json','source_garment.obj','SOURCE_LICENSE.txt','garment_assets.py']
    manifest.update(id=scene_name,name=spec['name']+' · '+variant,task_spec=spec,
        source_files=[str((dest/n).relative_to(ASSETS)) for n in source_names],status='TASK_SCENE_CANDIDATE',physics_rollout=False,task_success='unavailable')
    manifest['cloth'][0].update(mode=task+'/'+variant,physics_validated=False)
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    topology=cloth_mapping(stage,manifest['cloth'][0])
    if abs(topology['initial_max_edge_ratio']-1)>1e-4:raise ValueError('Initial state stretches the material mesh')
    layers,files,missing=UsdUtils.ComputeAllDependencies(str(dest/'scene.usda'))
    if set(missing)-{'OmniPBR.mdl'}:raise ValueError(str(missing))
    dependencies={Path(x.realPath) for x in layers}|{Path(x) for x in files}
    validation=dict(passed=True,physical_vertices=len(topology['rest_vertices']),initial_max_edge_ratio=topology['initial_max_edge_ratio'],
        physics_validated=False,dependencies_sha256={str(p.relative_to(ASSETS)):sha(p) for p in dependencies})
    (dest/'validation.json').write_text(json.dumps(validation,indent=2))
    def artifact(n,role):
        p=dest/n;return dict(source_id='robot-cloth-scenes-v1',path=str(p.relative_to(ASSETS)),role=role,sha256=sha(p),size_bytes=p.stat().st_size)
    registry=AssetRegistry();scn='SCN-rcloth-'+scene_name.replace('_','-');mdl='MDL-rcloth-'+scene_name.replace('_','-')
    common=dict(engines=['genesis','isaac_sim'],tags=['cloth','franka','folding-v3',task],
        description='第二批独立任务初态；物理动作与结果另存运行证据。',change_note='新增 folding_v3 场景。')
    drafts=[AssetDraft(asset_id=scn,kind='scene',name=manifest['name'],data=dict(task=task,variant=variant,status='TASK_SCENE_CANDIDATE',runnable_in_collector=False),
        artifacts=[artifact(n,r) for n,r in [('manifest.json','manifest'),('task_spec.json','configuration'),('builder.py','source')]],**common),
        AssetDraft(asset_id=mdl,kind='model',name=manifest['name']+' USD',data=dict(entrypoint=str((dest/'scene.usda').relative_to(ASSETS)),static_check=validation,physics_validated=False),
        references=[dict(asset_id=scn,version=1,role='scene')],artifacts=[artifact('scene.usda','scene'),artifact('validation.json','static_validation')],**common)]
    for draft in drafts:
        record,_=registry.publish(draft,expected_version=0,idempotent=True)
        if registry.integrity(record)['status']!='current':raise ValueError('Scene registration failed')
    print('SCENE_BUILT',scene_name,flush=True)
    return dest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--task',choices=TASKS);p.add_argument('--variant');a=p.parse_args()
    for task in [a.task] if a.task else TASKS:build(task,a.variant)
