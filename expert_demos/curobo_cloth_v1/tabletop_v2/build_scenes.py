"""Derive new immutable cloth initial states from the existing L workcell."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

HERE = Path(__file__).resolve().parent
CORE = HERE.parent
PROJECT = CORE.parents[1]
ASSETS = PROJECT / 'assets/sources/robot-cloth-scenes-v1'
sys.path.insert(0, str(CORE))
from tabletop_v2 import catalog, TASKS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def grid():
    return np.array([[u, v, 0.] for v in np.linspace(-.15, .15, 61)
                     for u in np.linspace(-.2, .2, 81)])


def transform(points, center, yaw):
    return Rotation.from_euler('z', yaw, degrees=True).apply(points) + np.r_[center, .784]


def initial_points(task, variant):
    cfg = catalog()['tasks'][task]['variants'][variant]
    material = grid()
    if task == 'edge_retrieve_spread':
        u = material[:, 0] + .2 - cfg['hanging_length_m']
        horizontal = np.maximum(u, 0) + np.minimum(u, 0) * np.cos(np.deg2rad(80))
        z = .786 + np.minimum(u, 0) * np.sin(np.deg2rad(80))
        if cfg['edge'] == 'front':
            return np.c_[cfg['edge_center'] - material[:, 1], -.702 + horizontal, z]
        return np.c_[.098 + horizontal, cfg['edge_center'] + material[:, 1], z]
    if task == 'directed_flatten':
        profiles = {
            'mild': [0,0,0,0,0,45,45,-45,-45,0,0,0,0,0,0,0,145,145,145,145],
            'folded': [0]*14 + [155]*6,
            'reverse': [145]*4 + [0]*8 + [-45]*2 + [45]*2 + [0]*4,
        }
        angles = np.repeat(np.deg2rad(profiles[cfg['profile']]), 4)
        u = np.r_[0, np.cumsum(.005 * np.cos(angles))]
        z = np.r_[0, np.cumsum(.005 * np.sin(angles))]
        u -= (u.min() + u.max()) / 2
        z -= z.min()
        local = np.array([[x, v, h] for v in np.linspace(-.15, .15, 61) for x, h in zip(u, z)])
        return transform(local, cfg['initial_center'], cfg['target_yaw_deg'])
    if task == 'translate_rotate_align':
        return transform(material, cfg['initial_center'], cfg['initial_yaw_deg'])
    # The hinge lies on existing diagonals of the physical grid. Rotating each
    # side rigidly preserves material lengths instead of stretching a corner.
    sign = 1 if cfg['corner_index'] == 20 else -1
    cut = .35 - cfg['fold_leg_m']
    distance = sign * (material[:, 0] - material[:, 1]) - cut
    folded = material.copy()
    normal = sign * np.array([1., -1., 0.]) / np.sqrt(2)
    axis = np.array([1., 1., 0.]) / np.sqrt(2)
    hinge = normal * cut / np.sqrt(2)
    selected = distance > 1e-9
    rotation = Rotation.from_rotvec(axis * np.deg2rad(-sign * cfg['fold_angle_deg']))
    folded[selected] = rotation.apply(material[selected] - hinge) + hinge
    return transform(folded, cfg['target_center'], cfg['target_yaw_deg'])


def task_spec(task, variant):
    book = catalog(); entry = book['tasks'][task]; cfg = entry['variants'][variant]
    target = transform(grid(), cfg['target_center'], cfg['target_yaw_deg'])
    ids = [0, 80, 60*81, 61*81-1]
    targets = {str(k): target[i, :2].tolist() for k, i in zip([0,20,315,335], ids)}
    return dict(id=task, batch_id='tabletop_v2', variant_id=variant, name=entry['name'],
                initial_parameters=cfg, target_table='B', source_table='B',
                target_region_xy_m=book['target_region_xy_m'],
                target_center_world_m=cfg['target_center']+[.78],
                target_yaw_deg=cfg['target_yaw_deg'], target_corners_xy_m=targets,
                target_outline_xy_m=[targets[str(i)] for i in [0,20,335,315,0]],
                required_stages=entry['required_stages'],
                primary_corner=cfg.get('corner_index', 335),
                workspace_low=[-.8,-.98,.50], workspace_high=[.85,.85,1.65],
                grasp_mode='local_soft_position_constraint', grasp_assistance_authorized=True,
                acceptance='Complete visibly effective task; coarse diagnostics plus explicit video review',
                assistance_strength=book['assisted_strength'])


def build(task, variant):
    from pxr import Usd, UsdGeom, UsdUtils, Vt
    from scene_adapter import cloth_mapping
    sys.path[:0] = [str(PROJECT/'backend/src'), str(PROJECT/'packages/robot-data-contracts/src')]
    from robot_data_contracts.asset import AssetDraft
    from robot_data_studio.services.asset_service import AssetRegistry
    dest = ASSETS/'scenes/tabletop_v2'/task/variant
    if dest.exists():
        manifest = json.loads((dest/'manifest.json').read_text())
        if manifest['task_spec'] != task_spec(task, variant):
            raise ValueError('Existing scene configuration differs; use a new variant')
        return dest
    dest.mkdir(parents=True)
    base = ASSETS/'scenes/l_table_transfer_mild'
    manifest = json.loads((base/'manifest.json').read_text())
    scene_name = 'ttv2_'+task+'_'+variant
    spec = task_spec(task, variant)
    stage = Usd.Stage.CreateNew(str(dest/'scene.usda'))
    stage.GetRootLayer().subLayerPaths = [str(base/'scene.usda')]
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, 'Z')
    points = initial_points(task, variant).astype(np.float32)
    cloth = UsdGeom.Mesh(stage.GetPrimAtPath(manifest['cloth'][0]['prim']))
    cloth.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points))
    ids = list(range(81))+[j*81+80 for j in range(1,61)]+list(range(4941-2,60*81-1,-1))+[j*81 for j in range(59,0,-1)]+[0]
    for prim in stage.GetPrimAtPath('/World').GetChildren():
        if prim.GetName().startswith('SewnHem'):
            UsdGeom.BasisCurves(prim).GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points[ids]))
        if prim.GetName().startswith('TargetOutline'):
            outline = np.array([p+[.781] for p in spec['target_outline_xy_m']], np.float32)
            UsdGeom.BasisCurves(prim).GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(outline))
    stage.GetRootLayer().customLayerData = dict(studio_status='TABLETOP_TASK_CANDIDATE', task_success='UNTESTED')
    stage.GetRootLayer().Save()
    (dest/'builder.py').write_bytes(Path(__file__).read_bytes())
    (dest/'catalog.json').write_bytes((HERE/'catalog.json').read_bytes())
    (dest/'task_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    manifest.update(id=scene_name, name=spec['name']+' · '+variant, task_spec=spec,
                    source_files=[str((dest/n).relative_to(ASSETS)) for n in ['builder.py','catalog.json','task_spec.json']],
                    status='TASK_SCENE_CANDIDATE', physics_rollout=False, task_success='unavailable')
    manifest['cloth'][0].update(mode=task+'/'+variant, physics_validated=False)
    (dest/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    topology = cloth_mapping(stage, manifest['cloth'][0])
    if abs(topology['initial_max_edge_ratio']-1) > 1e-4:
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
    common=dict(engines=['genesis','isaac_sim'], tags=['cloth','franka','l-table','tabletop-v2',task],
                description='同一写实 L 形工作台的独立任务初态；动态结果另存运行证据。', change_note='新增 tabletop_v2 场景，保留既有版本。')
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


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--task',choices=TASKS);parser.add_argument('--variant',default='v001')
    args=parser.parse_args()
    for task in ([args.task] if args.task else TASKS):build(task,args.variant)
