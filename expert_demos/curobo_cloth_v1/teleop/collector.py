"""Existing Collector browser protocol and canonical Franka episode recording."""
from http import HTTPStatus
import json
from pathlib import Path
import queue
import threading
import time
import numpy as np

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parents[2]


def capture_frame(output, state, renderer, stop, timeout=60):
    """Wait for the RGB rendered from this exact physics snapshot."""
    deadline = time.monotonic() + timeout
    while not stop.is_set():
        path = output / 'capture.npz'
        if path.exists():
            with np.load(path, allow_pickle=False) as packet:
                if int(packet['step']) == state['step'] and int(packet['reset_id']) == state['reset_id']:
                    return packet['rgb'].copy(), int(packet['capture_timestamp_ns'])
        if renderer.poll() is not None:
            raise RuntimeError('Isaac renderer exited; see isaac.log')
        if time.monotonic() > deadline:
            raise TimeoutError('Isaac frame did not match the requested physics state')
        stop.wait(.01)
    raise InterruptedError('Collection stopped')


class Collector:
    def __init__(self, host, port, ui_root, fps, dt, steps_per_control, width, height, rigid_only=False):
        self.host, self.port, self.ui_root = host, port, Path(ui_root)
        self.queue = queue.Queue(maxsize=256)
        self.jpeg = None
        self.current_episode = None
        self.task = '操纵刚体方块' if rigid_only else '操纵 ClothForge 衣物'
        self.writer = None
        self.saved = []
        self.message = {
            'scene_id': 'genesis_ipc_rigid_single' if rigid_only else 'genesis_ipc_clothforge_single',
            'scene_description': ('Genesis 刚体 + IPC 物理' if rigid_only else 'Genesis FEM Cloth + IPC 物理') + ' · Isaac Sim RTX 渲染',
            'default_task': self.task, 'control_mode': 'keyboard', 'dual_arm': False,
            'arm_ids': ['arm'], 'scene_catalog': [], 'resolved_scene_spec': {},
            'runtime': dict(control_fps=fps, sim_dt_s=dt, substeps=1,
                            physics_steps_per_control=steps_per_control, camera_resolution=[width, height]),
            'recording': False, 'episode': None, 'frames': 0, 'task': self.task,
            'stream_fps': 0, 'metrics': {}, 'log': 'Collector 启动中', 'ready': False,
        }
        self.server = None
        self.thread = None

    def update(self, **values):
        self.message = {**self.message, **values,
            'recording': bool(self.writer and self.writer.is_recording),
            'episode': self.current_episode,
            'frames': self.writer.frame_count if self.writer else 0, 'task': self.task}

    def create_writer(self, root, args, cfg, garment, scene_metadata):
        from robot_data_contracts import FrankaEpisodeWriter
        import genesis as gs
        from robot_data_contracts.profiles.franka import NATIVE_STATE_NAMES, NATIVE_ACTION_NAMES
        self.writer = FrankaEpisodeWriter(root, fps=args.control_fps, engine_id='isaac_sim',
            engine_version=scene_metadata['isaac_version'], scene_id=self.message['scene_id'],
            seed=cfg['seed'], worker_id='genesis_ipc_isaac_collector', control_source='browser_keyboard',
            operator_command_names=['dx_m', 'dy_m', 'dz_m', 'droll_rad', 'dpitch_rad', 'dyaw_rad', 'gripper_m'],
            state_names=NATIVE_STATE_NAMES, action_names=NATIVE_ACTION_NAMES, camera_names=['base'],
            run_metadata={
                'physics_backend': 'genesis_ipc', 'physics_engine_version': gs.__version__,
                'renderer': 'isaac_sim_rtx', 'assisted_grasp': False,
                **({'material': garment['material'], 'rest_geometry': garment['audit'],
                    'assets': [{'asset_id': args.parameters.get('garment_asset_id', garment['manifest']['id']),
                                'version': args.parameters.get('garment_version'),
                                'mesh_sha256': garment['manifest']['mesh_sha256']}],
                    'cloth_velocity_source': 'finite difference between captured physics snapshots'}
                   if garment is not None else {'rigid_object': {'shape': 'box', 'size_m': [.08]*3, 'fixed': True}, 'assets': []}),
                'camera_resolution': [args.width, args.height], 'camera_roles': {'base': 'agentview'},
                'camera_intrinsic_matrices': {'base': scene_metadata['intrinsics']},
                'camera_extrinsics': {'base': scene_metadata['extrinsics']},
                'camera_profile': {'id': 'genesis_ipc_isaac_single_v1'},
                'sim_dt_s': cfg['dt'], 'control_fps': args.control_fps,
                'physics_steps_per_control': round(1 / (args.control_fps * cfg['dt'])),
                'scene_parameters': args.parameters,
                'git_roots': {'studio': STUDIO, 'clothforge': STUDIO.parent / 'ClothForge'},
                'dependency_packages': ['genesis-world', 'pyuipc', 'numpy'],
            })

    def recording_command(self, command, task=None):
        if command == 'start':
            self.task = (task or self.task).strip()
            self.current_episode = self.writer.start(self.task)
            self.update(log=f'Episode {self.current_episode} 开始采集')
        elif command in ('success', 'failure'):
            if self.writer.frame_count == 0:
                raise ValueError('等待第一帧后再保存')
            path = self.writer.finish(operator_success=command == 'success', auto_success=None,
                episode_metrics={'frames': self.writer.frame_count}, evaluator_id='operator_only')
            self.saved.append(str(path))
            self.current_episode = None
            self.update(log=f'Episode 已保存：{path}')
        elif command == 'discard':
            self.writer.discard()
            self.current_episode = None
            self.update(log='已丢弃当前 Episode')
        else:
            raise ValueError('Unknown recording command')

    def add_frame(self, *, image, state, action, requested, safe, operator, sequence, source_ns, receive_ns, capture_ns, velocity):
        self.writer.add_frame(images={'base': image},
            state=np.r_[state['qpos'], state['qvel']].astype(np.float32),
            action=action, requested_action=requested, safe_action=safe, applied_action=action,
            operator_command=operator, sim_time=state['time'],
            control_sequence=sequence, control_timestamp_ns=source_ns,
            control_receive_timestamp_ns=receive_ns, capture_timestamp_ns=capture_ns,
            ee_pose=np.r_[state['hand'], state['hand_quat']],
            **({'cloth_particles': np.asarray(state['cloth_vertices'], dtype=np.float32),
                'cloth_particle_velocities': velocity.astype(np.float32)} if 'cloth_vertices' in state else
               {'object_pose': np.asarray(state['object_pose'], dtype=np.float32)}),
            extra_arrays={'physics_step': np.array([state['step']], dtype=np.int64),
                          'reset_id': np.array([state['reset_id']], dtype=np.int64)})
        self.update()

    def start(self):
        from websockets.sync.server import serve
        from websockets.exceptions import ConnectionClosed
        assets = {
            '/': ('text/html; charset=utf-8', HERE / 'controls.html'),
            '/collector_ui.css': ('text/css; charset=utf-8', self.ui_root / 'collector_ui.css'),
            '/collector_common.mjs': ('text/javascript; charset=utf-8', self.ui_root / 'collector_common.mjs'),
            '/keyboard_ui.mjs': ('text/javascript; charset=utf-8', self.ui_root / 'keyboard_ui.mjs'),
        }
        for _, path in assets.values():
            if not path.is_file():
                raise FileNotFoundError(path)
        def http(connection, request):
            if request.headers.get('Upgrade', '').lower() == 'websocket':
                return None
            path = request.path.split('?')[0]
            if path == '/status':
                response = connection.respond(HTTPStatus.OK, json.dumps(self.message))
                response.headers['Content-Type'] = 'application/json'
            elif path in assets:
                mime, source = assets[path]
                response = connection.respond(HTTPStatus.OK, source.read_text())
                response.headers['Content-Type'] = mime
            else:
                return connection.respond(HTTPStatus.NOT_FOUND, 'Not found')
            response.headers['Cache-Control'] = 'no-store'
            return response
        def client(ws):
            sequence = -1
            try:
                while True:
                    ws.send(json.dumps(self.message))
                    if self.jpeg:
                        ws.send(self.jpeg)
                    try:
                        data = json.loads(ws.recv(timeout=.1))
                    except TimeoutError:
                        continue
                    if data.get('type') in ('keydown', 'keyup'):
                        value = data.get('sequence')
                        if not isinstance(value, int) or value <= sequence:
                            raise ValueError('Keyboard sequence must increase')
                        sequence = value
                    if data.get('type') not in ('keydown', 'keyup', 'command', 'reconfigure'):
                        raise ValueError('Unsupported Collector message')
                    self.queue.put_nowait({**data, 'receive_ns': time.monotonic_ns()})
            except ConnectionClosed:
                pass
            except (ValueError, queue.Full) as error:
                ws.send(json.dumps({**self.message, 'log': str(error)}))
            finally:
                try:
                    self.queue.put_nowait({'type': 'release'})
                except queue.Full:
                    self.update(log='Input queue full while disconnecting')
        self.server = serve(client, self.host, self.port, process_request=http, max_size=65536)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        if self.writer and self.writer.is_recording:
            if self.writer.frame_count:
                self.writer.finish(operator_success=False, episode_metrics={'interrupted': True}, auto_success=None)
            else:
                self.writer.discard()
        if self.server:
            self.server.shutdown()
            self.thread.join(timeout=5)


def run(args, cfg, world, robot, native, garment, output, axis_audit, sync_audit, cube=None):
    import os
    import signal
    import subprocess
    from scipy.spatial.transform import Rotation
    from garment_ipc import positions
    from scene import array
    import torch

    def atomic(path, value):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False))
        temporary.replace(path)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    hand = robot.get_link('hand')
    initial_q = array(robot.get_qpos())
    targets, servo_positions = initial_q.copy(), initial_q.copy()
    limits = np.stack([array(x) for x in robot.get_dofs_limit()], axis=-1).reshape(9, 2)
    masses = array(robot.get_links_inertial_mass())
    hand_target, hand_quat = array(hand.get_pos()), array(hand.get_quat())
    pressed = set()
    reset_id = steps = 0
    sequence = source_ns = receive_ns = -1
    previous_vertices = None
    previous_time = None
    control_steps = round(1 / (args.control_fps * cfg['dt']))
    control_dt = cfg['dt'] * control_steps
    collector = Collector(args.host, args.port, args.collector_ui_root, args.control_fps,
                          cfg['dt'], control_steps, args.width, args.height, rigid_only=cube is not None)

    def snapshot():
        return dict(step=steps, reset_id=reset_id, time=steps * cfg['dt'],
            qpos=array(robot.get_qpos()).tolist(), qvel=array(robot.get_dofs_velocity()).tolist(),
            **({'cloth_vertices': positions(native).tolist()} if cube is None else
               {'object_pose': np.r_[array(cube.get_pos()), array(cube.get_quat())].tolist()}),
            hand=array(hand.get_pos()).tolist(),
            hand_quat=array(hand.get_quat()).tolist())

    atomic(output / 'state.json', snapshot())
    atomic(output / 'scene.json', dict(config=cfg, rigid_only=cube is not None,
        **({'faces': garment['faces'].tolist(), 'initial_vertices': garment['vertices'].tolist(),
            'garment': garment['manifest']['id'], 'material': garment['material'],
            'mapping': garment['mapping'], 'rest_geometry': garment['audit']} if garment is not None else
           {'cube_size': [.08]*3}),
        parameters=args.parameters, width=args.width, height=args.height, axis_compat=axis_audit))
    render_log = (output / 'isaac.log').open('w')
    renderer = subprocess.Popen([args.isaac_python, str(HERE / 'viewer.py'), '--output', str(output)],
        stdout=render_log, stderr=subprocess.STDOUT, start_new_session=True)
    trace = (output / 'commands.jsonl').open('a')
    timings = (output / 'timings.jsonl').open('a')
    started = time.monotonic()
    frame_count = 0
    try:
        state = snapshot()
        capture_frame(output, state, renderer, stop, timeout=540)
        metadata = json.loads((output / 'camera.json').read_text())
        collector.create_writer(args.episode_root, args, cfg, garment, metadata)
        collector.update(ready=True, log='Collector 已就绪')
        collector.start()
        started = time.monotonic()  # Exclude Isaac initialization from the displayed loop rate.
        print('COLLECTOR_READY', args.port, flush=True)
        while not stop.is_set() and (not args.max_steps or steps < args.max_steps):
            cycle_start = time.perf_counter()
            commands = []
            while not collector.queue.empty():
                event = collector.queue.get_nowait()
                trace.write(json.dumps({'step': steps, **event}) + '\n')
                trace.flush()
                kind = event.get('type')
                if kind == 'release':
                    pressed.clear()
                elif kind == 'reconfigure':
                    collector.update(log='请在 Studio 创建会话页选择衣物与材料后启动新会话')
                elif kind == 'command':
                    commands.append((event.get('command'), event.get('task')))
                elif kind in ('keydown', 'keyup'):
                    sequence = event['sequence']
                    source_ns = int(event.get('timestamp_ns', -1))
                    receive_ns = event['receive_ns']
                    code = event.get('code')
                    if kind == 'keyup':
                        pressed.discard(code)
                    elif code == 'Space':
                        targets[7:] = 0 if targets[7] > .02 else .04
                    elif code == 'KeyR':
                        commands.append(('reset', None))
                    elif code == 'KeyC':
                        commands.append(('success' if collector.writer.is_recording else 'start', event.get('task')))
                    elif code in ('KeyX', 'Backspace'):
                        commands.append(('failure' if code == 'KeyX' else 'discard', None))
                    else:
                        pressed.add(code)
            for command, task in commands:
                try:
                    if command == 'reset':
                        if collector.writer.is_recording:
                            raise ValueError('请先保存或丢弃当前 Episode，再复位')
                        world.reset()
                        # IPC's Python articulation caches are outside its frame-zero checkpoint.
                        coupler = world.sim.coupler
                        coupler._store_gs_rigid_states()
                        for entity, ad in coupler._articulation_data_by_entity.items():
                            initial = ad.qpos_stored.copy()
                            for value in (ad.ref_dof_prev, ad.qpos_current, ad.qpos_new):
                                value[:] = initial
                            ad.delta_theta_tilde[:] = 0
                            ad.delta_theta_ipc[:] = 0
                            for link, previous in zip(ad.joints_child_link, ad.prev_links_transform):
                                for env_idx in range(coupler.sim._B):
                                    previous[env_idx] = coupler._abd_transforms_by_link[link][env_idx].copy()
                        targets = array(robot.get_qpos())
                        servo_positions = targets.copy()
                        hand_target, hand_quat = array(hand.get_pos()), array(hand.get_quat())
                        pressed.clear()
                        reset_id += 1
                        previous_vertices = previous_time = None
                        collector.update(log='环境已复位')
                    else:
                        collector.recording_command(command, task)
                except (ValueError, RuntimeError) as error:
                    collector.update(log=str(error))
            if args.target_episodes and len(collector.saved) >= args.target_episodes:
                break
            operator = np.array([
                ('ArrowRight' in pressed) - ('ArrowLeft' in pressed),
                ('ArrowUp' in pressed) - ('ArrowDown' in pressed),
                ('KeyW' in pressed) - ('KeyS' in pressed),
                ('KeyQ' in pressed) - ('KeyE' in pressed), 0,
                ('KeyA' in pressed) - ('KeyD' in pressed), 0], dtype=float)
            operator[:3] *= .01
            operator[3:6] *= np.deg2rad(2)
            operator[6] = float(targets[7:].sum())
            if np.any(operator[:6]):
                candidate = hand_target + operator[:3]
                quat = (Rotation.from_rotvec(operator[3:6]) * Rotation.from_quat(hand_quat[[1, 2, 3, 0]])).as_quat()[[3, 0, 1, 2]]
                if not (-.5 <= candidate[0] <= .35 and -.5 <= candidate[1] <= .4 and .8 <= candidate[2] <= 1.4):
                    collector.update(log='目标超出工作区')
                else:
                    q, error = robot.inverse_kinematics(link=hand, pos=candidate, quat=quat,
                        init_qpos=targets, dofs_idx_local=np.arange(7), max_samples=1, return_error=True)
                    if np.linalg.norm(array(error)[:3]) > .005 or np.linalg.norm(array(error)[3:]) > .05:
                        collector.update(log='目标不可达，保持上一目标')
                    else:
                        hand_target, hand_quat = candidate, quat
                        targets[:7] = array(q)[:7]
            snapshot_start = time.perf_counter()
            state = snapshot()
            atomic(output / 'state.json', state)
            snapshot_ms = (time.perf_counter() - snapshot_start) * 1000
            increment = np.r_[np.full(7, .35 * control_dt), [.04 * control_dt] * 2]
            servo_positions += np.clip(targets - servo_positions, -increment, increment)
            servo_positions = np.clip(servo_positions, limits[:, 0], limits[:, 1])
            torque = np.zeros(robot.n_dofs)
            for link, mass in zip(robot.links, masses):
                if mass > 0:
                    jacobian = array(robot.get_jacobian(link, local_point=np.array(link.inertial_pos)))
                    torque -= jacobian[:3].T @ np.array([0., 0., -9.81 * float(mass)])
            motor_target = servo_positions.copy()
            motor_target[:7] += torque[:7] / np.array(cfg['kp'])[:7]
            motor_target = np.clip(motor_target, limits[:, 0], limits[:, 1])
            recording = collector.writer.is_recording
            wait_ms = writer_ms = 0.
            if recording:
                wait_start = time.perf_counter()
                image, capture_ns = capture_frame(output, state, renderer, stop)
                wait_ms = (time.perf_counter() - wait_start) * 1000
                writer_start = time.perf_counter()
                vertices = np.asarray(state['cloth_vertices']) if cube is None else None
                velocity = (np.zeros_like(vertices) if previous_vertices is None else
                    (vertices - previous_vertices) / (state['time'] - previous_time)) if cube is None else None
                collector.add_frame(image=image, state=state, action=motor_target, requested=targets,
                    safe=servo_positions, operator=operator, sequence=sequence, source_ns=source_ns,
                    receive_ns=receive_ns, capture_ns=capture_ns, velocity=velocity)
                previous_vertices, previous_time = (vertices.copy() if vertices is not None else None), state['time']
                writer_ms = (time.perf_counter() - writer_start) * 1000
            else:
                previous_vertices = previous_time = None
            preview = output / 'preview.jpg'
            if preview.exists():
                collector.jpeg = preview.read_bytes()
            frame_count += 1
            robot.control_dofs_position(motor_target - initial_q)
            torch.cuda.synchronize()
            physics_start = time.perf_counter()
            for _ in range(control_steps):
                if stop.is_set() or (args.max_steps and steps >= args.max_steps):
                    break
                world.step()
                steps += 1
            torch.cuda.synchronize()
            physics_ms = (time.perf_counter() - physics_start) * 1000
            render_state_path = output / 'render-state.json'
            rendered = json.loads(render_state_path.read_text()) if render_state_path.exists() else {}
            measured = dict(step=state['step'], reset_id=reset_id, recording=recording,
                physics_ms=physics_ms, snapshot_ms=snapshot_ms, frame_wait_ms=wait_ms, writer_ms=writer_ms,
                cycle_ms=(time.perf_counter() - cycle_start) * 1000,
                render_ms=rendered.get('render_ms'), rendered_step=rendered.get('step'))
            timings.write(json.dumps(measured) + '\n')
            timings.flush()
            collector.update(metrics={'physics_step': steps, 'saved_episodes': len(collector.saved),
                **{k: round(v, 1) for k,v in measured.items() if k.endswith('_ms') and v is not None}},
                stream_fps=frame_count / max(.001, time.monotonic() - started))
            if renderer.poll() is not None:
                raise RuntimeError('Isaac renderer exited; see isaac.log')
    except InterruptedError:
        if not stop.is_set():
            raise
    finally:
        collector.update(ready=False)
        collector.close()
        trace.close()
        timings.close()
        try:
            os.killpg(renderer.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            renderer.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(renderer.pid, signal.SIGKILL)
            renderer.wait()
        render_log.close()
        atomic(output / 'run-summary.json', dict(steps=steps, state_sync_steps=sync_audit['steps'],
            saved_episodes=collector.saved, renderer_exit_code=renderer.returncode))
