"""Build immutable task scenes with actual fixture collision geometry."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;CORE=HERE.parent;PROJECT=CORE.parents[1]
ASSETS=PROJECT/'assets/sources/robot-cloth-scenes-v1'
BATCH=PROJECT/'data/expert_demos/curobo-cloth-v1/fixtures_v4'
sys.path.insert(0,str(CORE))
from fixtures_v4 import TASKS,catalog
from fixtures_v4.initial_states import grid,transform,initial_points,parent_run,lineage
from fixtures_v4.fixtures import add_to_stage

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def task_spec(task,variant,parent=None):
    book=catalog();entry=book['tasks'][task];cfg=entry['variants'][variant]
    if parent is None and task.startswith('retrieve_'):parent=parent_run(BATCH,task,variant)
    target=transform(grid(),cfg['target_center']);ids=[0,80,60*81,61*81-1]
    corners={str(k):target[i,:2].tolist() for k,i in zip([0,20,315,335],ids)}
    fixture=dict(book['fixtures'][cfg['fixture']],kind=cfg['fixture'],center_xy=cfg['fixture_center_xy'])
    return dict(id=task,batch_id='fixtures_v4',variant_id=variant,name=entry['name'],initial_parameters=cfg,
        fixture=fixture,initial_state=lineage(parent),target_table='B',source_table='A' if task in ('cover_box','retrieve_from_rod','retrieve_from_basket') else 'B',
        target_region_xy_m=book['target_region_xy_m'],target_center_world_m=cfg['target_center']+[.78],
        target_yaw_deg=90,target_corners_xy_m=corners,target_outline_xy_m=[corners[str(i)] for i in [0,20,335,315,0]],
        required_stages=entry['required_stages'],primary_corner=cfg['primary_corner'],
        workspace_low=[-.8,-.98,.50],workspace_high=[.85,.85,1.65],
        grasp_mode='local_soft_position_constraint',grasp_assistance_authorized=True,
        acceptance='Visible complete manipulation and released terminal state; physical diagnostics and actual saved-frame review',
        assistance_strength=book['assisted_strength'],max_assisted_nodes=1)

def build(task, variant):
    from pxr import Usd, UsdGeom, UsdUtils, Vt
    from scene_adapter import cloth_mapping
    sys.path[:0] = [str(PROJECT/'backend/src'), str(PROJECT/'packages/robot-data-contracts/src')]
    from robot_data_contracts.asset import AssetDraft
    from robot_data_studio.services.asset_service import AssetRegistry
    dest = ASSETS/'scenes/fixtures_v4'/task/variant
    if dest.exists():
        manifest = json.loads((dest/'manifest.json').read_text())
        if manifest['task_spec']['initial_parameters'] != catalog()['tasks'][task]['variants'][variant]:
            raise ValueError('Existing scene configuration differs; use a new variant')
        return dest
    parent=parent_run(BATCH,task,variant)
    dest.mkdir(parents=True)
    base = ASSETS/'scenes/l_table_transfer_mild'
    manifest = json.loads((base/'manifest.json').read_text())
    scene_name = 'fxv4_'+task+'_'+variant
    spec = task_spec(task, variant, parent)
    stage = Usd.Stage.CreateNew(str(dest/'scene.usda'))
    stage.GetRootLayer().subLayerPaths = [str(base/'scene.usda')]
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, 'Z')
    points = initial_points(task, catalog()['tasks'][task]['variants'][variant], parent).astype(np.float32)
    add_to_stage(stage,spec)
    cloth = UsdGeom.Mesh(stage.GetPrimAtPath(manifest['cloth'][0]['prim']))
    cloth.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points))
    ids = list(range(81))+[j*81+80 for j in range(1,61)]+list(range(4941-2,60*81-1,-1))+[j*81 for j in range(59,0,-1)]+[0]
    for prim in stage.GetPrimAtPath('/World').GetChildren():
        if prim.GetName().startswith('SewnHem'):
            UsdGeom.BasisCurves(prim).GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points[ids]))
        if prim.GetName().startswith('TargetOutline'):
            outline = np.array([p+[.781] for p in spec['target_outline_xy_m']], np.float32)
            UsdGeom.BasisCurves(prim).GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(outline))
    stage.GetRootLayer().customLayerData = dict(studio_status='FIXTURE_TASK_CANDIDATE', task_success='UNTESTED')
    stage.GetRootLayer().Save()
    (dest/'builder.py').write_bytes(Path(__file__).read_bytes())
    (dest/'catalog.json').write_bytes((HERE/'catalog.json').read_bytes())
    for name in ['fixtures.py','initial_states.py']:(dest/name).write_bytes((HERE/name).read_bytes())
    (dest/'initial_state.json').write_text(json.dumps(lineage(parent),indent=2))
    (dest/'task_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    manifest.update(id=scene_name, name=spec['name']+' · '+variant, task_spec=spec,
                    source_files=[str((dest/n).relative_to(ASSETS)) for n in ['builder.py','catalog.json','task_spec.json','fixtures.py','initial_states.py','initial_state.json']],
                    status='TASK_SCENE_CANDIDATE', physics_rollout=False, task_success='unavailable')
    manifest['cloth'][0].update(mode=task+'/'+variant, physics_validated=False)
    (dest/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    topology = cloth_mapping(stage, manifest['cloth'][0])
    if parent is None and abs(topology['initial_max_edge_ratio']-1) > 1e-4:
        raise ValueError('Initial fold stretches the physical mesh')
    layers, files, missing = UsdUtils.ComputeAllDependencies(str(dest/'scene.usda'))
    if set(missing)-{'OmniPBR.mdl'}:
        raise ValueError(str(missing))
    dependencies = {Path(x.realPath) for x in layers} | {Path(x) for x in files}
    validation = dict(passed=True, physical_grid=topology['physical_grid'],
                      initial_max_edge_ratio=topology['initial_max_edge_ratio'],
                      physics_validated=False, dependencies_sha256={str(p.relative_to(ASSETS)):sha(p) for p in dependencies})
    (dest/'validation.json').write_text(json.dumps(validation, indent=2))
    def artifact(name, role):
        p = dest/name
        return dict(source_id='robot-cloth-scenes-v1', path=str(p.relative_to(ASSETS)), role=role, sha256=sha(p), size_bytes=p.stat().st_size)
    registry = AssetRegistry(); scn='SCN-rcloth-'+scene_name.replace('_','-'); mdl='MDL-rcloth-'+scene_name.replace('_','-')
    common=dict(engines=['genesis','isaac_sim'], tags=['cloth','franka','l-table','fixtures-v4',task],
                description='原 L 形工作台增加实体横杆、敞口筐或盒子的独立初态；动态结果另存运行证据。', change_note='新增 fixtures_v4 场景，保留既有版本。')
    drafts = [AssetDraft(asset_id=scn, kind='scene', name=manifest['name'],
                        data=dict(task=task, variant=variant, status='TASK_SCENE_CANDIDATE', runnable_in_collector=False),
                        artifacts=[artifact(n,r) for n,r in [('manifest.json','manifest'),('task_spec.json','configuration'),('builder.py','source')]], **common),
              AssetDraft(asset_id=mdl, kind='model', name=manifest['name']+' USD',
                         data=dict(entrypoint=str((dest/'scene.usda').relative_to(ASSETS)), static_check=validation, physics_validated=False),
                         references=[dict(asset_id=scn,version=1,role='scene')],
                         artifacts=[artifact('scene.usda','scene'),artifact('validation.json','static_validation')], **common)]
    for draft in drafts:
        rec,_=registry.publish(draft, expected_version=0, idempotent=True)
        if registry.integrity(rec)['status'] != 'current': raise ValueError('Scene registration failed')
    print('SCENE_BUILT', scene_name, flush=True)
    return dest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--task',choices=TASKS,required=True);parser.add_argument('--variant',default='v001')
    args=parser.parse_args();build(args.task,args.variant)
