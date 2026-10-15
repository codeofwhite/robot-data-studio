"""Render a canonical Genesis Episode with Isaac; never advance physics."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from uuid import uuid4

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--gpu', type=int, required=True)
args = parser.parse_args()
source, output = args.source.resolve(), args.output.resolve()
output.mkdir(parents=True, exist_ok=True)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)

manifest = json.loads((source / 'manifest.json').read_text())
source_hashes = {name: digest(source / name) for name in ['manifest.json', 'trajectory.npz']}
replay = manifest['scene']['parameters']['offline_replay']
write(output / 'progress.json', {'status':'starting', 'frame':0, 'total':manifest['num_frames']})
from isaacsim import SimulationApp
app = SimulationApp({'headless':True, 'active_gpu':args.gpu, 'physics_gpu':0,
    'multi_gpu':False, 'renderer':'RaytracedLighting', 'limit_cpu_threads':4,
    'enable_crashreporter':False,
    'extra_args':['--/app/useFabricSceneDelegate=false', '--/renderer/multiGpu/autoEnable=false',
                  '--/app/settings/persistent=false', '--/log/file='+str(output / 'kit.log')]})
exit_code = 1
try:
    import numpy as np
    from PIL import Image
    from scipy.spatial.transform import Rotation
    from pxr import Usd, UsdGeom, UsdPhysics, UsdLux, Gf, Vt
    import omni.usd
    import omni.replicator.core as rep
    core = Path(__file__).resolve().parent
    studio = core.parents[1]
    sys.path.insert(0, str(studio / 'packages/robot-data-contracts/src'))
    from robot_data_contracts.validation import inspect_episode
    from robot_data_contracts.episode import EpisodeManifestV1
    inspect_episode(source / 'manifest.json', engine_id='genesis')
    with np.load(source / 'trajectory.npz', allow_pickle=False) as z:
        data = {k:z[k] for k in z.files}
    assets = studio / 'assets/sources/robot-cloth-scenes-v1'
    spec = importlib.util.spec_from_file_location('expert_builder', assets / 'build_scenes.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    sys.path.insert(0, str(core / 'tabletop_v2'))
    from cached_visual_robot import CachedFrankaPose
    stage = Usd.Stage.CreateNew(str(output / 'render.usda'))
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, 'Z')
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, '/World').GetPrim())
    builder = object.__new__(module.Builder)
    builder.s, builder.out, builder.i, builder.robot_reports, builder.m = stage, output, 0, [], {}
    for name,color in [('white',(.52,.39,.27)),('floor',(.2,.22,.25)),('object',(.1,.55,.8)),('cloth',(.9,.24,.27)),('target',(.2,.7,.3))]:
        builder.m[name] = builder.material(name, color, .7, 0)
    geometry = manifest['scene']['parameters']['scene_geometry']
    scene_spec = geometry['resolved_scene_spec']
    builder.box('Floor',(0,0,-.025),(10,10,.05),'floor')
    builder.box('Table',geometry['table_center_m'],geometry['table_size_m'])
    if 'work_surface_center_m' in geometry:
        builder.box('WorkSurface',geometry['work_surface_center_m'],geometry['work_surface_size_m'])
    table_top = geometry.get('work_surface_top_m', geometry['table_center_m'][2]+geometry['table_size_m'][2]/2)
    if 'object_color_rgba' in scene_spec:
        builder.m['object'] = builder.material('ObjectSource', tuple(scene_spec['object_color_rgba'][:3]), .7, 0)
        builder.m['target'] = builder.material('TargetSource', tuple(scene_spec['target_color_rgba'][:3]), .7, 0)
    cloth = None
    if 'cloth' in replay:
        cloth = builder.mesh('Cloth',data['cloth_particles'][0],replay['cloth']['faces'],'cloth')
        xy = geometry['corner_marker_xy_m']
        builder.box('CornerMarker',(*xy,table_top+.002),(.055,.055,.004),'object')
        object_prim = None
    else:
        object_prim = builder.box('Object',data['object_pose'][0,:3].astype(float).tolist(),[scene_spec['object_size_m']]*3,'object')
        bin_spec = scene_spec.get('bin')
        bx,by = scene_spec['target_xy_m']
        if bin_spec:
            sx,sy=bin_spec['outer_size_xy_m'];wall=bin_spec['wall_thickness_m'];height=bin_spec['height_m']
            for i,(p,size) in enumerate([
                ((bx,by,table_top+wall/2),(sx,sy,wall)),
                ((bx-sx/2+wall/2,by,table_top+height/2),(wall,sy,height)),
                ((bx+sx/2-wall/2,by,table_top+height/2),(wall,sy,height)),
                ((bx,by-sy/2+wall/2,table_top+height/2),(sx,wall,height)),
                ((bx,by+sy/2-wall/2,table_top+height/2),(sx,wall,height))]):
                builder.box('Bin'+str(i),p,size,'target')
        else:
            builder.box('Target',(bx,by,table_top+.002),[*scene_spec['target_size_xy_m'],.004],'target')
    joint_names = ['panda_joint'+str(i) for i in range(1,8)]+['panda_finger_joint1','panda_finger_joint2']
    def joints(q):
        return {name:float(np.rad2deg(v) if i<7 else v) for i,(name,v) in enumerate(zip(joint_names,q))}
    builder.robot('Franka',assets/'robots/franka/franka.usd',replay['robot_base_position_m'],0,joints(data['native_state'][0,:9]))
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).CreateRigidBodyEnabledAttr(False)
    UsdLux.DomeLight.Define(stage,'/World/Light').CreateIntensityAttr(1200)
    UsdLux.DistantLight.Define(stage,'/World/Key').CreateIntensityAttr(2000)
    camera_paths = {}
    for name, cfg in replay['cameras'].items():
        width,height=cfg['resolution'];k=np.asarray(cfg['intrinsics'])
        if not np.allclose([k[0,2],k[1,2]],[width/2,height/2],atol=1e-4):
            raise ValueError('This renderer requires a centered pinhole camera')
        camera=UsdGeom.Camera.Define(stage,'/World/Camera_'+name)
        focal=float(k[0,0])*24/width
        camera.CreateFocalLengthAttr(focal);camera.CreateHorizontalApertureAttr(24)
        camera.CreateVerticalApertureAttr(focal*height/float(k[1,1]))
        camera.CreateClippingRangeAttr(Gf.Vec2f(.01,100))
        camera.AddTransformOp().Set(Gf.Matrix4d(np.asarray(data[cfg['pose_array']][0]).T))
        camera_paths[name]=camera.GetPath()
    stage.GetRootLayer().Save();omni.usd.get_context().open_stage(str(output/'render.usda'))
    stage=omni.usd.get_context().get_stage()
    pose=CachedFrankaPose(stage,'Franka')
    if cloth is not None:cloth=UsdGeom.Mesh(stage.GetPrimAtPath(cloth.GetPath()))
    if object_prim:
        obj=UsdGeom.Xformable(stage.GetPrimAtPath(object_prim.GetPath()));obj.ClearXformOpOrder();obj_transform=obj.AddTransformOp()
    cameras={name:UsdGeom.Camera(stage.GetPrimAtPath(path)) for name,path in camera_paths.items()}
    annotators={}
    for name,camera in cameras.items():
        product=rep.create.render_product(str(camera.GetPath()),replay['cameras'][name]['resolution'])
        annotator=rep.AnnotatorRegistry.get_annotator('rgb');annotator.attach([product]);annotators[name]=annotator
    bodies=[p for p in Usd.PrimRange(stage.GetPrimAtPath('/World/Franka')) if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    mappings={};offsets={};max_position_error=0.;max_rotation_error=0.
    def verify_robot(frame):
        global max_position_error,max_rotation_error
        recorded=data['robot_link_poses'][frame];cache=UsdGeom.XformCache()
        for body in bodies:
            m=np.asarray(cache.GetLocalToWorldTransform(body)).T
            rotation=Rotation.from_matrix(m[:3,:3]);name=body.GetName()
            if frame==0:
                candidates=np.flatnonzero(np.linalg.norm(recorded[:,:3]-m[:3,3],axis=1)<.0005)
                if not len(candidates):raise ValueError('USD robot link has no recorded counterpart: '+name)
                def rotation_error(j):
                    return (Rotation.from_quat(recorded[j,[4,5,6,3]]).inv()*rotation).magnitude()
                index=int(min(candidates,key=rotation_error));mappings[name]=index
                offset=Rotation.from_quat(recorded[index,[4,5,6,3]]).inv()*rotation
                allowed={'panda_link8':np.pi/4,'panda_rightfinger':np.pi}
                if offset.magnitude()>.003 and (name not in allowed or abs(offset.magnitude()-allowed[name])>.003):
                    raise ValueError('Unexpected robot link-frame rotation: '+name)
                offsets[name]=offset
            row=recorded[mappings[name]];pe=float(np.linalg.norm(row[:3]-m[:3,3]))
            expected=Rotation.from_quat(row[[4,5,6,3]])*offsets[name]
            re=float((rotation*expected.inv()).magnitude())
            if pe>.0005 or re>.003:raise ValueError(f'Robot frame mismatch {name}: {pe} m, {re} rad')
            max_position_error=max(max_position_error,pe);max_rotation_error=max(max_rotation_error,re)
    staging=output/'episode_000000.tmp';staging.mkdir()
    for name in manifest['camera_names']:(staging/(name+'_rgb')).mkdir()
    for _ in range(20):app.update()
    for frame in range(manifest['num_frames']):
        pose.apply(joints(data['native_state'][frame,:9]));verify_robot(frame)
        if cloth is not None:
            cloth.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(data['cloth_particles'][frame].astype(np.float32)))
        else:
            row=data['object_pose'][frame];rotation=Gf.Matrix4d().SetRotate(Gf.Quatd(float(row[3]),Gf.Vec3d(*map(float,row[4:]))))
            transform=Gf.Matrix4d().SetScale(Gf.Vec3d(*([scene_spec['object_size_m']]*3)))*rotation
            transform.SetTranslateOnly(Gf.Vec3d(*map(float,row[:3])));obj_transform.Set(transform)
        for name,camera in cameras.items():
            matrix=data[replay['cameras'][name]['pose_array']][frame]
            camera.GetOrderedXformOps()[0].Set(Gf.Matrix4d(matrix.T))
        app.update();rep.orchestrator.step(delta_time=0,pause_timeline=False,rt_subframes=2)
        for name,annotator in annotators.items():
            rgb=np.asarray(annotator.get_data())
            if rgb.ndim!=3 or not rgb.size:raise RuntimeError('Empty Isaac image: '+name)
            Image.fromarray(rgb[:,:,:3]).save(staging/(name+'_rgb')/f'{frame:06d}.jpg',quality=95)
        write(output/'progress.json',{'status':'rendering','frame':frame+1,'total':manifest['num_frames']})
        print('EPISODE_RENDER_PROGRESS',frame+1,manifest['num_frames'],flush=True)
    if any(digest(source/name)!=value for name,value in source_hashes.items()):
        raise ValueError('Source Episode changed during rendering')
    shutil.copyfile(source/'trajectory.npz',staging/'trajectory.npz')
    derived=json.loads(json.dumps(manifest));derived['episode_uuid']=str(uuid4());derived['episode_index']=0
    derived['created_at']=datetime.now(timezone.utc).isoformat()
    derived['lineage']={'parent_episode_uuid':manifest['episode_uuid'],'generation_method':'visual_rerender',
        'trajectory_modified':False,'randomization_spec_id':None,'resolved_parameters':{'renderer':'isaac_sim_rtx','source_hashes':source_hashes}}
    derived['scene']['parameters']['render_assets'] = [
        {'path':str(path), 'sha256':digest(path)} for path in
        [Path(__file__).resolve(), assets/'build_scenes.py', assets/'robots/franka/franka.usd', core/'tabletop_v2/cached_visual_robot.py']]
    derived['scene']['parameters'].update(image_renderer='Isaac Sim RTX',source_episode_uuid=manifest['episode_uuid'],
        source_episode_path=str(source),source_hashes=source_hashes,replay_only=True,physics_executed=False,
        image_timestamp_semantics='original observation time; offline rendering executes no physics')
    derived['software']['worker_id']='isaac_offline_episode_renderer'
    derived['software']['dependencies']['isaacsim']=(Path(sys.executable).resolve().parents[3]/'VERSION').read_text().strip()
    for name in derived['camera_names']:
        derived['camera_calibration'][name]['intrinsics']=np.asarray(replay['cameras'][name]['intrinsics']).ravel().tolist()
        derived['camera_calibration'][name]['extrinsics']={'camera_to_world_array':replay['cameras'][name]['pose_array'],'axes':replay['camera_axes'],'dynamic':name=='wrist'}
    validated=EpisodeManifestV1.model_validate(derived)
    (staging/'manifest.json').write_text(validated.model_dump_json(indent=2))
    inspect_episode(staging/'manifest.json',engine_id='genesis')
    staging.rename(output/'episode_000000')
    result={'status':'completed','episode_path':str(output/'episode_000000'),'source_hashes':source_hashes,
            'trajectory_sha256':digest(output/'episode_000000/trajectory.npz'),'frames':manifest['num_frames'],
            'max_robot_position_error_m':max_position_error,'max_robot_rotation_error_rad':max_rotation_error,
            'physics_steps':0,'renderer_gpu':args.gpu}
    write(output/'render-result.json',result);write(output/'progress.json',result)
    exit_code=0
except BaseException:
    error=traceback.format_exc();print(error,file=sys.stderr,flush=True)
    write(output/'render-result.json',{'status':'failed','error':error})
finally:
    app.close(exit_code=exit_code)
