"""Isaac RTX display-only replay; robot FK and cloth vertices checked against measured states."""
import argparse,json,os,sys,hashlib,subprocess,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ASSETS=ROOT.parents[1]/'assets/sources/robot-cloth-scenes-v1'
p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--gpu',type=int,default=3);p.add_argument('--max-frames',type=int);p.add_argument('--output-name',default='pbr_replay')
p.add_argument('--camera',choices=['hero','detail','overhead','grasp'],default='hero')
p.add_argument('--output-dir',type=Path);p.add_argument('--appearance-file',type=Path);p.add_argument('--cached-robot',action='store_true');a=p.parse_args()
run=Path(a.run).resolve();out=a.output_dir.resolve() if a.output_dir else run/a.output_name;out.mkdir(parents=True,exist_ok=False);cache=out/'cache';cache.mkdir()
appearance_spec=json.loads(a.appearance_file.read_text()) if a.appearance_file else None
(out/'renderer_source.py').write_bytes(Path(__file__).read_bytes())
(out/'scene_adapter_source.py').write_bytes((ROOT/'scene_adapter.py').read_bytes())
(out/'frame_mapping_source.py').write_bytes((ROOT/'render_replay.py').read_bytes())
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':a.gpu,'physics_gpu':0 if os.environ.get('CUDA_VISIBLE_DEVICES','').isdigit() else a.gpu,'multi_gpu':False,'renderer':'PathTracing','width':960,'height':960,
 'enable_crashreporter':False,'limit_cpu_threads':6,
 'extra_args':['--/app/useFabricSceneDelegate=false','--/rtx/hydra/supportMultiTickRate=false','--/app/settings/persistent=false',
 '--/renderer/multiGpu/autoEnable=false','--/renderer/multiGpu/activeGpus='+str(a.gpu),'--/renderer/multiGpu/maxGpuCount=1',
 '--/app/userConfigPath='+str(cache/'user.config.json'),'--/app/cachePath='+str(cache/'kit'),'--/app/dataPath='+str(cache/'data'),'--/log/file='+str(cache/'kit.log')]})
encoder=None
try:
 import numpy as np
 from PIL import Image
 from pxr import Usd,UsdGeom,UsdShade,UsdLux,Gf,Sdf,Vt
 from scipy.spatial.transform import Rotation
 import omni.usd,omni.replicator.core as rep,carb
 cfg=json.loads((run/'config.json').read_text())
 # NpzFile is lazy: indexing it every frame would decompress the entire cloth
 # array repeatedly. Cache measured states once, as the delivered renderer does.
 loaded=np.load(run/'trajectory.npz',allow_pickle=False)
 # folding_v3 supplies an already frozen dict through its recorded-state cache.
 if isinstance(loaded,dict):data=loaded
 else:
  with loaded as archive:data={key:archive[key] for key in archive.files}
 for array in data.values():array.setflags(write=False)
 topology=json.loads((run/'physical_scene/assets/cloth_topology.json').read_text())
 binding=cfg.get('scene_binding')
 if binding:
  from scene_adapter import verify_scene_sources
  verify_scene_sources(binding);ASSETS=Path(binding['snapshot_root'])
 spec=importlib.util.spec_from_file_location('_frozen_visual_builder',ASSETS/'build_scenes.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 if binding:
  stage=Usd.Stage.CreateNew(str(out/'scene.usda'))
  UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,'Z')
  stage.GetRootLayer().subLayerPaths=[str(ASSETS/binding['usd_relative_path'])]
  b=object.__new__(mod.Builder);b.s=stage;b.out=out;b.i=0;b.m={};b.robot_reports=[]
  cloth=UsdGeom.Mesh(stage.GetPrimAtPath(binding['dynamic_cloth']['prim']))
  original_points=np.asarray(cloth.GetPointsAttr().Get(),float)
  visual_indices=np.asarray(topology['visual_indices']);visual_weights=np.asarray(topology['visual_weights'])
  secondary=[]
  from scipy.spatial import cKDTree
  tree=cKDTree(original_points)
  import re
  backing_prefix=re.sub(r'\d+$','',cloth.GetPrim().GetName())+'Backing'
  for prim in stage.GetPrimAtPath('/World').GetChildren():
   if prim.IsA(UsdGeom.BasisCurves):
    attr=UsdGeom.BasisCurves(prim).GetPointsAttr();pts=np.asarray(attr.Get(),float);dist,ids=tree.query(pts)
    if dist.max()<1e-5:secondary.append((str(prim.GetPath()),'curve',ids,pts-original_points[ids]))
   elif prim.IsA(UsdGeom.Mesh) and re.sub(r'\d+$','',prim.GetName())==backing_prefix:
    pts=np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get(),float)
    if pts.shape!=original_points.shape:raise RuntimeError('Cloth backing topology differs')
    secondary.append((str(prim.GetPath()),'mesh',np.arange(len(pts)),pts-original_points))
  robot_name=binding['active_robot']
 else:
  stage=Usd.Stage.CreateNew(str(out/'scene.usda'));UsdGeom.SetStageUpAxis(stage,'Z');UsdGeom.SetStageMetersPerUnit(stage,1)
  stage.SetDefaultPrim(UsdGeom.Xform.Define(stage,'/World').GetPrim())
  b=object.__new__(mod.Builder);b.s=stage;b.out=out;b.i=0;b.m={};b.robot_reports=[];b.top=cfg['table_height'];b.spec=('physics_replay','physical replay','lab','single','cotton','flat')
  for name,color,rough,metal in [('white',(.77,.79,.78),.36,0),('dark',(.025,.032,.04),.4,.4),('floor',(.28,.3,.32),.85,0),('wall',(.63,.66,.65),.82,0),('steel',(.42,.45,.48),.3,.85)]:
   b.m[name]=b.material(name,color,rough,metal)
  b.m['wood']=b.material('Oak',(.5,.35,.18),.5,0,'oak.png')
  b.m['cloth']=b.material('Cloth',(.08,.28,.31),.9,0,'cotton_color.png','cotton_normal.png')
  # Helper texture paths are designed for the static asset tree; resolve them explicitly here.
  for prim in stage.Traverse():
   if prim.IsA(UsdShade.Shader):
    attr=prim.GetAttribute('inputs:file')
    if attr and attr.Get():attr.Set(Sdf.AssetPath(str(ASSETS/'textures'/Path(attr.Get().path).name)))
  # Exactly the physical tabletop dimensions and pose; props only below the work surface.
  pos=np.asarray(cfg['table']['position']);dim=2*np.asarray(cfg['table']['half_extents'])
  # Six independently UV-mapped box faces.
  verts=[];faces=[];uv=[]
  for axis in range(3):
   other=[x for x in range(3) if x!=axis]
   for sign in [-1,1]:
    start=len(verts)
    for u,v in [(-1,-1),(1,-1),(1,1),(-1,1)]:
     pt=pos.copy();pt[axis]+=sign*dim[axis]/2;pt[other[0]]+=u*dim[other[0]]/2;pt[other[1]]+=v*dim[other[1]]/2
     verts.append(pt);uv.append([(u+1)*1.5,(v+1)*1.5])
    faces.append([start,start+1,start+2,start+3])
  b.mesh('Table',verts,faces,'wood',uv)
  b.box('Floor',(0,0,-.06),(8,8,.02),'floor')
  for x in [-.75,.75]:
   for y in [-.47,.47]:b.box('Leg',(x,y,.355),(.045,.045,.71),'dark')
  b.box('Wall',(0,2.2,1.4),(8,.08,2.8),'wall')
  rest=np.asarray(topology['rest_vertices']);uv=(rest[:,:2]-rest[:,:2].min(axis=0))/cfg['square']['width_m']
  cloth=b.mesh('PhysicalCloth',data['cloth_vertices'][0],topology['faces'],'cloth',uv)
  robot_name='Franka'
 if appearance_spec:
  appearance=appearance_spec['appearance']
  if hashlib.sha256((run/'trajectory.npz').read_bytes()).hexdigest()!=appearance_spec['source_trajectory_sha256']:raise ValueError('Appearance source trajectory changed')
  sys.path.insert(0,str(ROOT.parents[1]/'packages/robot-data-contracts/src'))
  from robot_data_contracts.usd_material import create_material
  material=create_material(stage,'/World/Materials/AppearanceOverride',appearance)
  uv=UsdGeom.PrimvarsAPI(cloth).GetPrimvar('st')
  if not uv or not uv.HasValue():
   rest=original_points if binding else np.asarray(topology['rest_vertices'])
   span=np.ptp(rest[:,:2],axis=0);coords=(rest[:,:2]-rest[:,:2].min(axis=0))/np.maximum(span,1e-6)
   UsdGeom.PrimvarsAPI(cloth).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,'vertex').Set(Vt.Vec2fArray.FromNumpy(coords.astype(np.float32)))
  UsdShade.MaterialBindingAPI.Apply(cloth.GetPrim()).Bind(material,bindingStrength=UsdShade.Tokens.strongerThanDescendants)
  if binding:
   for path,kind,ids,offset in secondary:
    if kind=='mesh':
     prim=stage.GetPrimAtPath(path)
     UsdShade.MaterialBindingAPI.Apply(prim).Bind(material,bindingStrength=UsdShade.Tokens.strongerThanDescendants)
     UsdGeom.PrimvarsAPI(prim).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,'vertex').Set(uv.Get() if uv and uv.HasValue() else Vt.Vec2fArray.FromNumpy(coords.astype(np.float32)))
 environment=appearance_spec.get('environment') if appearance_spec else None
 sys.path.insert(0,str(ROOT.parents[1]/'packages/robot-data-contracts/src'))
 from robot_data_contracts.usd_surface import apply_environment,replay_targets
 environment_surfaces=apply_environment(stage,environment,replay_targets(stage,binding))
 for module in ('usd_material','usd_surface'):
  (out/(module+'_source.py')).write_bytes((ROOT.parents[1]/'packages/robot-data-contracts/src/robot_data_contracts'/(module+'.py')).read_bytes())
 qnames=['panda_joint'+str(i) for i in range(1,8)]+['panda_finger_joint1','panda_finger_joint2']
 pose_cache={}
 if a.cached_robot:
  sys.path.insert(0,str(ROOT/'tabletop_v2'))
  from cached_visual_robot import CachedFrankaPose
 def pose_robot(q):
  qs={n:float(v*180/np.pi if i<7 else v) for i,(n,v) in enumerate(zip(qnames,q))}
  if a.cached_robot and pose_cache:
   if pose_cache.get('stage')!=stage:pose_cache.update(stage=stage,pose=CachedFrankaPose(stage,robot_name))
   pose_cache['pose'].apply(qs)
   return
  b.robot(robot_name,ASSETS/'robots/franka/franka.usd',cfg['bases'][0],cfg['yaws'][0],qs)
  if a.cached_robot:
   pose_cache.update(stage=stage,pose=CachedFrankaPose(stage,robot_name))
   pose_cache['pose'].apply(qs)
 pose_robot(data['qpos'][0,0])
 # Verify corresponding rigid-body transforms against recorded physical links.
 robot=stage.GetPrimAtPath('/World/'+robot_name)
 from pxr import UsdPhysics
 bodies=[x for x in Usd.PrimRange(robot) if x.HasAPI(UsdPhysics.RigidBodyAPI)]
 mapping={};frame_offsets={}
 def verify_fk(snapshot,initial=False):
  cache=UsdGeom.XformCache();record=np.asarray(snapshot)
  maxp=maxr=0.
  for body in bodies:
   matrix=np.asarray(cache.GetLocalToWorldTransform(body)).T;pos=matrix[:3,3];rot=Rotation.from_matrix(matrix[:3,:3])
   errs=[]
   for r in record:
    rr=Rotation.from_quat(r[[4,5,6,3]])
    errs.append(np.linalg.norm(pos-r[:3])+(rot*rr.inv()).magnitude()*.1)
   name=body.GetName()
   if initial:
    distances=np.linalg.norm(record[:,:3]-pos,axis=1);candidates=np.flatnonzero(distances<.0003)
    if len(candidates)==0:raise RuntimeError('No physical position matches '+name)
    mapping[name]=int(min(candidates,key=lambda j:errs[j]))
    rec=record[mapping[name]];rr=Rotation.from_quat(rec[[4,5,6,3]])
    offset=(rr.inv()*rot)
    allowed={'panda_link8':np.pi/4,'panda_rightfinger':np.pi}
    if offset.magnitude()>.003 and (name not in allowed or abs(offset.magnitude()-allowed[name])>.003):
     raise RuntimeError('Unexpected USD/MJCF fixed-frame rotation: '+name+' '+str(offset.as_rotvec()))
    frame_offsets[name]=offset.as_quat().tolist()
   rec=record[mapping[name]];pe=float(np.linalg.norm(pos-rec[:3]))
   expected=Rotation.from_quat(rec[[4,5,6,3]])*Rotation.from_quat(frame_offsets[name])
   re=float((rot*expected.inv()).magnitude())
   if pe>.0003 or re>.003:raise RuntimeError(f'USD/physics body mismatch {name}: {pe}m {re}rad')
   maxp=max(maxp,pe);maxr=max(maxr,re)
  return maxp,maxr
 verify_fk(data['link_poses'][0,0],True)
 c=cfg['camera']['front']
 if binding:
  if a.camera=='grasp':
   goal=json.loads((run/'grasp_goal.json').read_text());target=np.asarray(goal['material_position']);pos=target+[.45,-.6,.38]
   camera_transform=Gf.Matrix4d().SetLookAt(Gf.Vec3d(*pos),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse()
   aperture=36.;focal=50.;camera_source='derived close-up of recorded material grasp point'
  else:
   source_camera=stage.GetPrimAtPath('/World/Cameras/'+a.camera)
   if not source_camera:raise RuntimeError('Original camera missing: '+a.camera)
   source_camera_geom=UsdGeom.Camera(source_camera)
   aperture=float(source_camera_geom.GetHorizontalApertureAttr().Get());focal=float(source_camera_geom.GetFocalLengthAttr().Get())
   camera_transform=UsdGeom.XformCache().GetLocalToWorldTransform(source_camera);camera_source=str(source_camera.GetPath())
  cam=UsdGeom.Camera.Define(stage,'/World/Camera')
  cam.CreateHorizontalApertureAttr(aperture);cam.CreateVerticalApertureAttr(aperture)
  cam.CreateFocalLengthAttr(focal);cam.CreateClippingRangeAttr(Gf.Vec2f(.01,50))
  cam.AddTransformOp().Set(camera_transform)
 else:
  dome=UsdLux.DomeLight.Define(stage,'/World/Dome');dome.CreateIntensityAttr(400)
  for name,pos,target,size,intensity,color in [('Key',(-1.5,-1.8,2.6),(-.1,0,.8),(2,1.5),2000,(1,.94,.86)),('Fill',(1.8,-.4,2.3),(-.1,0,.8),(1.5,1.5),1300,(.86,.92,1)),('Rim',(-.5,1,2.4),(-.1,0,.8),(1,.6),1500,(1,1,1))]:
   l=UsdLux.RectLight.Define(stage,'/World/'+name);l.CreateWidthAttr(size[0]);l.CreateHeightAttr(size[1]);l.CreateIntensityAttr(intensity);l.CreateColorAttr(Gf.Vec3f(*color))
   l.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*pos),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse())
  c=cfg['camera']['front'];cam=UsdGeom.Camera.Define(stage,'/World/Camera');cam.CreateHorizontalApertureAttr(36);cam.CreateVerticalApertureAttr(36)
  cam.CreateFocalLengthAttr(18/np.tan(np.deg2rad(c['fov']/2)));cam.CreateClippingRangeAttr(Gf.Vec2f(.01,50))
  cam.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*c['pos']),Gf.Vec3d(*c['lookat']),Gf.Vec3d(*c['up'])).GetInverse())
 # TransformPrimCommand targets the active Kit stage, so open this replay
 # stage before applying camera poses rather than editing the detached stage.
 stage.GetRootLayer().Save();omni.usd.get_context().open_stage(str(out/'scene.usda'))
 stage=omni.usd.get_context().get_stage();b.s=stage;cloth=UsdGeom.Mesh(stage.GetPrimAtPath(cloth.GetPath()));robot=stage.GetPrimAtPath('/World/'+robot_name);bodies=[x for x in Usd.PrimRange(robot) if x.HasAPI(UsdPhysics.RigidBodyAPI)]
 camera_lighting=appearance_spec.get('camera_lighting') if appearance_spec else None
 from robot_data_contracts.camera_lighting import validate_resolved
 from robot_data_contracts.usd_camera_lighting import apply_camera,apply_lighting,apply_imaging
 validate_resolved(camera_lighting)
 visual_values=camera_lighting['values'] if camera_lighting else {}
 camera_lighting_applied={'cameras':{'front':apply_camera(stage,'/World/Camera',visual_values,960,960)},
                          'lights':apply_lighting(stage,visual_values)}
 for module in ('camera_lighting','usd_camera_lighting'):
  (out/(module+'_source.py')).write_bytes((ROOT.parents[1]/'packages/robot-data-contracts/src/robot_data_contracts'/(module+'.py')).read_bytes())
 stage.GetRootLayer().Save()
 settings=carb.settings.get_settings();settings.set('/rtx/rendermode','PathTracing');settings.set('/rtx/pathtracing/spp',32);settings.set('/rtx/pathtracing/totalSpp',32);settings.set('/rtx/pathtracing/maxBounces',6);settings.set('/rtx/pathtracing/optixDenoiser/enabled',True);settings.set('/rtx/post/tonemap/op',6)
 camera_lighting_applied['imaging']=apply_imaging(settings,visual_values)
 rep.orchestrator.set_capture_on_play(False)
 for _ in range(40):app.update()
 product=rep.create.render_product('/World/Camera',(960,960));rgb=rep.AnnotatorRegistry.get_annotator('rgb');rgb.attach(product)
 from render_replay import exact_frames
 frame_rows=exact_frames(data['tick'],int(data['tick'][-1]),cfg['dt'],10)
 ticks={int(t):i for i,t in enumerate(data['tick'])};frames=[row['tick'] for row in frame_rows]
 if binding:(out/'front_frames').mkdir()
 if a.max_frames:frames=frames[:a.max_frames]
 for t in frames:
  if t not in ticks:raise RuntimeError('Missing exact physical snapshot')
 encoder=subprocess.Popen(['/data/zhanghejun/miniconda3/envs/genesis/bin/python','-B',str(ROOT/'encode_video.py'),str(out/'front.mp4'),'960','960','10'],stdin=subprocess.PIPE)
 frame_map=[];maxp=maxr=0.
 for frame,tick in enumerate(frames):
  i=ticks[tick];pose_robot(data['qpos'][i,0]);pe,re=verify_fk(data['link_poses'][i,0]);maxp=max(maxp,pe);maxr=max(maxr,re)
  physical=np.asarray(data['cloth_vertices'][i],np.float32)
  points=np.sum(physical[visual_indices]*visual_weights[:,:,None],axis=1).astype(np.float32) if binding else physical
  cloth.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points))
  if not np.array_equal(np.asarray(cloth.GetPointsAttr().Get()),points):raise RuntimeError('Rendered cloth points differ from recorded state mapping')
  if binding:
   if not np.array_equal(points[topology['source_vertex_ids']],physical):raise RuntimeError('Physical cloth nodes differ from original USD visual nodes')
   for path,kind,ids,offset in secondary:
    obj=stage.GetPrimAtPath(path);attr=(UsdGeom.Mesh(obj) if kind=='mesh' else UsdGeom.BasisCurves(obj)).GetPointsAttr()
    attr.Set(Vt.Vec3fArray.FromNumpy((points[ids]+offset).astype(np.float32)))
  # Appearance batches use the same two updates and 32 spp as the delivered
  # folding_v3 fast renderer; exact poses are still checked on every frame.
  if appearance_spec:
   for _ in range(1):app.update()
   rep.orchestrator.step(delta_time=0,pause_timeline=False,rt_subframes=1)
  else:
   for _ in range(2):app.update()
   rep.orchestrator.step(delta_time=0,pause_timeline=False,rt_subframes=4)
  arr=np.asarray(rgb.get_data()).copy()[:,:,:3]
  if arr.shape!=(960,960,3) or arr.std()<2:raise RuntimeError('Empty PBR render')
  encoder.stdin.write(np.ascontiguousarray(arr).tobytes())
  frame_artifact={}
  if binding:
   jpeg=out/'front_frames'/f'{frame:06d}.jpg';Image.fromarray(arr).save(jpeg,quality=95)
   frame_artifact={'image_path':str(jpeg.relative_to(out)),'image_sha256':hashlib.sha256(jpeg.read_bytes()).hexdigest()}
  if frame in {0,len(frames)//2,len(frames)-1}:Image.fromarray(arr).save(out/f'front_{frame:05d}.png')
  frame_map.append({'frame':frame,'tick':tick,'sample':i,'simulation_time_s':tick*cfg['dt'],'video_time_s':frame/10,**frame_artifact})
  if frame%25==0:print('PBR_PROGRESS',frame,len(frames),flush=True)
 encoder.stdin.close()
 if encoder.wait(timeout=60)!=0:raise RuntimeError('Video encoder failed')
 visual_files=list((ASSETS/'robots/franka').rglob('*'))+[ASSETS/'textures'/n for n in ['oak.png','cotton_color.png','cotton_normal.png']]
 visual_hashes=binding['source_sha256'] if binding else {str(p.relative_to(ASSETS)):hashlib.sha256(p.read_bytes()).hexdigest() for p in visual_files if p.is_file()}
 camera_info=camera_lighting_applied['cameras']['front']
 report={'camera':camera_info,'visual_asset_sha256':visual_hashes,'renderer':'Isaac RTX PathTracing','spp':32,'resolution':[960,960],'physics_steps':0,'cloth_vertices_exact':True,
   'stage_meters_per_unit':float(UsdGeom.GetStageMetersPerUnit(stage)),'stage_up_axis':str(UsdGeom.GetStageUpAxis(stage)),
   'robot_body_max_position_error_m':maxp,'robot_body_max_rotation_error_rad':maxr,'link_mapping':mapping,'fixed_frame_offsets_xyzw':frame_offsets,'frame_map':frame_map,
   'trajectory_sha256':hashlib.sha256((run/'trajectory.npz').read_bytes()).hexdigest(),'renderer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
   'video':json.loads((out/'front.json').read_text()),'preview_only':a.max_frames is not None,'review_status':'SELF_REVIEWED_PROVISIONAL'}
 if binding:report.update(scene=binding['scene'],scene_binding_sha256=hashlib.sha256((run/'scene_binding.json').read_bytes()).hexdigest(),
  original_scene_loaded=True,source_camera=camera_source,cloth_mapping='barycentric physical surface; exact node correspondence; backing and sewn hem follow the same surface',
  cloth_topology_sha256=hashlib.sha256((run/'physical_scene/assets/cloth_topology.json').read_bytes()).hexdigest(),passive_robots=binding['passive_robots'])
 if appearance_spec:report.update(appearance=appearance_spec['appearance'],appearance_spec=appearance_spec,render_updates_per_frame=2,
                                  environment=environment,environment_surfaces=environment_surfaces,
                                  camera_lighting=camera_lighting,camera_lighting_applied=camera_lighting_applied)
 (out/'verification.json').write_text(json.dumps(report,indent=2));print('PBR_COMPLETE',json.dumps({k:v for k,v in report.items() if k not in ['frame_map','link_mapping']}),flush=True)
 rgb.detach(product);product.destroy()
except BaseException:
 import traceback
 error=traceback.format_exc();(out/'failure.txt').write_text(error);print(error,flush=True)
 raise
finally:
 if encoder is not None and encoder.poll() is None:encoder.terminate()
 app.close()
