"""Display live Genesis states with the expert trajectory's Isaac/USD renderer."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
output = args.output.resolve()
core = Path(__file__).resolve().parents[1]
studio = core.parents[1]
assets = studio / 'assets/sources/robot-cloth-scenes-v1'
scene = json.loads((output / 'scene.json').read_text())
width, height = scene['width'], scene['height']
from isaacsim import SimulationApp
# Vulkan retains physical ordinals while CUDA renumbers the one visible device.
render_gpu = int(os.environ.get('CUDA_VISIBLE_DEVICES', '0'))
app = SimulationApp({'headless': True, 'active_gpu': render_gpu, 'physics_gpu': 0, 'multi_gpu': False,
    'renderer': 'RaytracedLighting', 'width': width, 'height': height,
    'enable_crashreporter': False, 'limit_cpu_threads': 4,
    'extra_args': ['--/app/useFabricSceneDelegate=false', '--/renderer/multiGpu/autoEnable=false',
                   '--/app/settings/persistent=false', '--/log/file=' + str(output / 'kit.log')]})
try:
    import numpy as np
    from PIL import Image
    from pxr import Usd, UsdGeom, UsdPhysics, UsdLux, Gf, Vt
    import omni.usd
    import omni.replicator.core as rep
    spec = importlib.util.spec_from_file_location('expert_visual_builder', assets / 'build_scenes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.insert(0, str(core / 'tabletop_v2'))
    from cached_visual_robot import CachedFrankaPose
    cfg = scene['config']
    initial = json.loads((output / 'state.json').read_text())
    stage = Usd.Stage.CreateNew(str(output / 'live_scene.usda'))
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, 'Z')
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, '/World').GetPrim())
    builder = object.__new__(module.Builder)
    builder.s = stage
    builder.out = output
    builder.i = 0
    builder.robot_reports = []
    builder.m = {}
    for name, color in [('white', (.64, .44, .25)), ('floor', (.18, .20, .23)), ('cloth', (.12, .40, .57))]:
        builder.m[name] = builder.material(name, color, .8, 0)
    builder.box('Table', cfg['table']['position'], (2 * np.asarray(cfg['table']['half_extents'])).tolist())
    builder.box('Floor', (0, 0, -.05), (4, 4, .1), 'floor')
    names = ['panda_joint' + str(i) for i in range(1, 8)] + ['panda_finger_joint1', 'panda_finger_joint2']
    def joint_map(values):
        return {name: float(np.rad2deg(value) if i < 7 else value) for i, (name, value) in enumerate(zip(names, values))}
    builder.robot('Franka', assets / 'robots/franka/franka.usd', cfg['bases'][0], 0, joint_map(initial['qpos']))
    rigid_only = scene.get('rigid_only', False)
    if rigid_only:
        cube_path = builder.box('Cube', initial['object_pose'][:3], scene['cube_size'], 'cloth').GetPath()
    else:
        cloth = builder.mesh('ClothForge', initial['cloth_vertices'], scene['faces'], 'cloth')
    # Render-only stage: disable authored dynamics. All motion comes from Genesis.
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).CreateRigidBodyEnabledAttr(False)
    UsdLux.DomeLight.Define(stage, '/World/Light').CreateIntensityAttr(1000)
    light = UsdLux.DistantLight.Define(stage, '/World/Key')
    light.CreateIntensityAttr(2500)
    UsdGeom.Xformable(light).AddRotateXYZOp().Set(Gf.Vec3f(315, 20, 20))
    camera = UsdGeom.Camera.Define(stage, '/World/Camera')
    camera.CreateFocalLengthAttr(24)
    camera.CreateHorizontalApertureAttr(24)
    camera.CreateVerticalApertureAttr(24 * height / width)
    camera.CreateClippingRangeAttr(Gf.Vec2f(.01, 100))
    camera.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(-.05, -1.6, 1.85),
        Gf.Vec3d(-.15, 0, .85), Gf.Vec3d(0, 0, 1)).GetInverse())
    # This standalone installation has a VERSION file, not an isaacsim dist-info.
    isaac_root = Path(sys.executable).resolve().parents[3]
    camera_metadata = {'renderer_gpu': render_gpu, 'isaac_version': (isaac_root / 'VERSION').read_text().strip(),
        'intrinsics': [width, 0., width / 2, 0., width, height / 2, 0., 0., 1.],
        'extrinsics': {'camera_to_world': np.asarray(camera.GetLocalTransformation()).T.tolist(),
                       'convention': 'USD camera axes, SI units'}}
    (output / 'camera.json').write_text(json.dumps(camera_metadata))
    stage.GetRootLayer().Save()
    omni.usd.get_context().open_stage(str(output / 'live_scene.usda'))
    stage = omni.usd.get_context().get_stage()
    if rigid_only:
        cube_xform = UsdGeom.Xformable(stage.GetPrimAtPath(cube_path))
        cube_xform.ClearXformOpOrder()
        cube_transform = cube_xform.AddTransformOp()
    else:
        cloth = UsdGeom.Mesh(stage.GetPrimAtPath(cloth.GetPath()))
    pose = CachedFrankaPose(stage, 'Franka')
    product = rep.create.render_product('/World/Camera', (width, height))
    rgb = rep.AnnotatorRegistry.get_annotator('rgb')
    rgb.attach([product])
    for _ in range(20):
        app.update()
    previous = None
    while app.is_running():
        state = json.loads((output / 'state.json').read_text())
        identity = (state.get('reset_id', 0), state['step'])
        if identity == previous:
            app.update()
            time.sleep(.03)
            continue
        previous = identity
        render_start = time.perf_counter()
        pose.apply(joint_map(state['qpos']))
        if rigid_only:
            p, q = state['object_pose'][:3], state['object_pose'][3:]
            transform = Gf.Matrix4d().SetRotate(Gf.Quatd(q[0], Gf.Vec3d(*q[1:])))
            transform = Gf.Matrix4d().SetScale(Gf.Vec3d(*scene['cube_size'])) * transform
            transform.SetTranslateOnly(Gf.Vec3d(*p))
            cube_transform.Set(transform)
        else:
            cloth.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(np.asarray(state['cloth_vertices'], dtype=np.float32)))
        app.update()
        rep.orchestrator.step(delta_time=0, pause_timeline=False, rt_subframes=2)
        image = np.asarray(rgb.get_data())
        if image.ndim != 3 or not image.size:
            raise RuntimeError('Isaac RGB annotator returned no image')
        temporary = output / 'capture.tmp.npz'
        np.savez(temporary, rgb=image[:, :, :3], step=np.int64(state['step']),
                 reset_id=np.int64(state.get('reset_id', 0)), capture_timestamp_ns=np.int64(time.monotonic_ns()))
        os.replace(temporary, output / 'capture.npz')
        temporary = output / 'preview.tmp.jpg'
        Image.fromarray(image[:, :, :3]).save(temporary, quality=85)
        os.replace(temporary, output / 'preview.jpg')
        if not (output / 'first-frame.jpg').exists():
            Image.fromarray(image[:, :, :3]).save(output / 'first-frame.jpg')
        temporary = output / 'render-state.tmp'
        temporary.write_text(json.dumps({'step': state['step'], 'reset_id': state.get('reset_id', 0),
                                         'renderer': 'Isaac Sim RTX', 'physics_steps': 0,
                                         'render_ms': (time.perf_counter() - render_start) * 1000}))
        os.replace(temporary, output / 'render-state.json')
except BaseException:
    import traceback
    diagnostic = traceback.format_exc()
    (output / 'viewer-error.txt').write_text(diagnostic)
    print(diagnostic, file=sys.stderr, flush=True)
    raise
finally:
    app.close()
