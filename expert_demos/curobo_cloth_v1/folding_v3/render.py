"""Recorded-state render: cache arrays and interpolate shading normals without moving vertices."""
import hashlib,json,os,sys,runpy
from pathlib import Path
import numpy as np

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 if os.environ.get('CUDA_VISIBLE_DEVICES')!='0,1':raise RuntimeError('Required GPU visibility: 0,1')
 args=sys.argv[1:];run=Path(args[0]).resolve();root=Path(__file__).resolve().parent.parent
 selected=None
 fps=10
 if '--video-fps' in args:
  index=args.index('--video-fps');fps=int(args[index+1]);del args[index:index+2]
  if fps not in (2,5,10):raise ValueError('Use an exact snapshot-compatible video rate: 2, 5, or 10')
 cached_robot='--uncached-robot' not in args
 if '--cached-robot' in args:args.remove('--cached-robot')
 if '--uncached-robot' in args:args.remove('--uncached-robot')
 fast='--slow-render' not in args
 if '--fast-render' in args:args.remove('--fast-render')
 if '--slow-render' in args:args.remove('--slow-render')
 if '--select-tick' in args:
  index=args.index('--select-tick');selected=int(args[index+1]);del args[index:index+2]
  if '--max-frames' not in args:args+=['--max-frames','1']
 name=args[args.index('--output-name')+1] if '--output-name' in args else 'pbr_replay'
 code_dir=run/(name+'_render_code');code_dir.mkdir()
 original=root/'render_pbr.py';base=original.read_text()
 (code_dir/'original_render_pbr.py').write_text(base)
 source=base.replace('ROOT=Path(__file__).resolve().parent','ROOT=Path('+repr(str(root))+')',1)
 if fps!=10:
  replacements={"cfg['dt'],10)":"cfg['dt'],"+str(fps)+")", "'960','960','10']":"'960','960',"+repr(str(fps))+"]", "'video_time_s':frame/10":"'video_time_s':frame/"+str(fps)}
  for old,new in replacements.items():
   if source.count(old)!=1:raise RuntimeError('Video-rate renderer marker changed: '+old)
   source=source.replace(old,new,1)
 marker="  physical=np.asarray(data['cloth_vertices'][i],np.float32)"
 addition="""  physical=np.asarray(data['cloth_vertices'][i],np.float32)
  # Area-weighted physical vertex normals, interpolated onto the recorded visual mesh.
  # Positions, faces, and physical states remain exactly those of the source replay.
  face_ids=np.asarray(topology['faces'],dtype=np.int64)
  tri=physical[face_ids];face_normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
  physical_normals=np.zeros_like(physical)
  for corner in range(3):np.add.at(physical_normals,face_ids[:,corner],face_normals)
  physical_normals/=np.maximum(np.linalg.norm(physical_normals,axis=1,keepdims=True),1e-12)
  visual_normals=np.sum(physical_normals[visual_indices]*visual_weights[:,:,None],axis=1).astype(np.float32) if binding else physical_normals
  visual_normals/=np.maximum(np.linalg.norm(visual_normals,axis=1,keepdims=True),1e-12)
  cloth.CreateNormalsAttr().Set(Vt.Vec3fArray.FromNumpy(visual_normals));cloth.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
"""
 if source.count(marker)!=1:raise RuntimeError('Renderer frame marker changed')
 source=source.replace(marker,addition,1)
 if fast:
  source=source.replace('  for _ in range(2):app.update()', '  for _ in range(1):app.update()').replace('rt_subframes=4','rt_subframes=1')
 if cached_robot:
  cached_source=root/'tabletop_v2/cached_visual_robot.py'
  (code_dir/'cached_visual_robot.py').write_bytes(cached_source.read_bytes())
  marker=" qnames=['panda_joint'+str(i) for i in range(1,8)]+['panda_finger_joint1','panda_finger_joint2']"
  source=source.replace(marker," from cached_visual_robot import CachedFrankaPose\n pose_cache={}\n"+marker,1)
  old="  b.robot(robot_name,ASSETS/'robots/franka/franka.usd',cfg['bases'][0],cfg['yaws'][0],qs)"
  new="  if not pose_cache:b.robot(robot_name,ASSETS/'robots/franka/franka.usd',cfg['bases'][0],cfg['yaws'][0],qs)\n  if pose_cache.get('stage')!=stage:pose_cache.update(stage=stage,pose=CachedFrankaPose(stage,robot_name))\n  pose_cache['pose'].apply(qs)"
  if source.count(old)!=1:raise RuntimeError('Original robot posing marker changed')
  source=source.replace(old,new,1)
  sys.path.insert(0,str(code_dir))
 derived=code_dir/'render_pbr.py';derived.write_text(source)
 target=run/'trajectory.npz';digest=sha(target);load=np.load
 with load(target) as archive:arrays={key:archive[key] for key in archive.files}
 if sha(target)!=digest:raise RuntimeError('Trajectory changed during preload')
 for array in arrays.values():array.setflags(write=False)
 def cached(file,*a,**kw):
  return arrays if isinstance(file,(str,os.PathLike)) and Path(file).resolve()==target else load(file,*a,**kw)
 np.load=cached;sys.path.insert(0,str(root))
 if selected is not None:
  import render_replay
  sample=int(np.flatnonzero(arrays['tick']==selected)[0])
  def exact(ticks,last,dt,fps):return [{'frame':0,'tick':selected,'sample':sample,'simulation_time_s':selected*dt,'video_time_s':0.,'applied_command_row_tick':selected+1}]
  render_replay.exact_frames=exact
 (run/(name+'_cache_source.py')).write_bytes(Path(__file__).read_bytes())
 (run/(name+'_cache_invocation.json')).write_text(json.dumps({'entrypoint_sha256':sha(__file__),'original_renderer_sha256':sha(original),'executed_renderer_sha256':sha(derived),'trajectory_sha256':digest,'CUDA_VISIBLE_DEVICES':'0,1','args':args,'selected_tick':selected,'video_fps':fps,'fast_render':fast,'cached_robot_fk':cached_robot,'spp':32,'render_updates_per_frame':2 if fast else 6,'geometry_policy':'Exact recorded cloth positions; only vertex shading normals interpolated. No smoothing of physical positions.','arrays':{k:{'shape':list(v.shape),'dtype':str(v.dtype),'sha256':hashlib.sha256(v.tobytes()).hexdigest()} for k,v in arrays.items()}},indent=2))
 sys.argv=[str(derived),*args]
 try:runpy.run_path(str(derived),run_name='__main__')
 finally:np.load=load
 # Isaac's outer script catches BaseException and may still exit with code 0.
 # Completion is the saved verification artifact, not the process exit code.
 report_path=run/name/'verification.json'
 if not report_path.exists():raise RuntimeError('Renderer ended without verification; inspect '+str(run/name/'failure.txt'))
 report=json.loads(report_path.read_text())
 if report['trajectory_sha256']!=digest:raise RuntimeError('Renderer verification belongs to a different trajectory')
if __name__=='__main__':main()
