"""Measured friction-only acquisition. Geometry is evidence, never a constraint."""
import json
import numpy as np
from scipy.spatial.transform import Rotation


def verify_foundation(path):
    """Reject a missing, incomplete or changed matched-control foundation."""
    import hashlib
    from pathlib import Path
    value = json.loads(Path(path).read_text())
    if value.get('passed') is not True or value.get('physics_passed') is not True:
        raise ValueError('Matched physical foundation has not passed')
    if (value.get('video_review_pending') is not False or not value.get('checks')
            or not all(value['checks'].values()) or len(value.get('evaluation_sha256', [])) != 2):
        raise ValueError('Foundation review is incomplete')
    for key, digest in zip(('positive', 'negative'), value['evaluation_sha256']):
        evaluation = Path(value[key]) / 'evaluation.json'
        if hashlib.sha256(evaluation.read_bytes()).hexdigest() != digest:
            raise ValueError('Foundation evaluation changed: ' + key)
        result = json.loads(evaluation.read_text())
        for name, expected in result['input_sha256'].items():
            if hashlib.sha256((evaluation.parent / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Foundation input changed: ' + name)
        verification = Path(value[key]) / 'pbr_replay/verification.json'
        render = json.loads(verification.read_text())
        if render.get('physics_steps') != 0 or not render.get('cloth_vertices_exact') or render.get('preview_only'):
            raise ValueError('Foundation recorded-state video is invalid')
    return value


def local_points(points, pose):
    pose = np.asarray(pose)
    return Rotation.from_quat(pose[[4, 5, 6, 3]]).inv().apply(np.asarray(points) - pose[:3])


def pad_face_distances(points, pose):
    """Distance to the unchanged MJCF pad's inward rectangular face, y=0."""
    p = local_points(points, pose)
    dx = np.maximum(np.abs(p[:, 0]) - .0085, 0.)
    dz = np.maximum(np.abs(p[:, 2] - .0445) - .009, 0.)
    return np.sqrt(dx * dx + p[:, 1] ** 2 + dz * dz)


def patch_pad_distance(vertices, faces, ids, pose):
    """Conservative upper bound: pad-face samples to nearby material triangles.

    Two mesh rings retain the continuous material next to the target corner,
    excluding a distant layer that happens to lie at the same world position.
    Sample-to-surface distance overestimates the true surface distance; it
    cannot make a distant surface look closer than it is.
    """
    import trimesh
    faces = np.asarray(faces, int)
    first_ring = faces[np.isin(faces, ids).any(axis=1)]
    if not len(first_ring):
        raise ValueError('Target material vertex has no incident triangle')
    patch = faces[np.isin(faces, np.unique(first_ring)).any(axis=1)]
    local = np.array([[x, 0., z] for x in np.linspace(-.0085, .0085, 9)
                      for z in np.linspace(.0355, .0535, 13)])
    pose = np.asarray(pose)
    world = Rotation.from_quat(pose[[4, 5, 6, 3]]).apply(local) + pose[:3]
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices), faces=patch, process=False)
    _, distances, _ = trimesh.proximity.closest_point_naive(mesh, world)
    return float(distances.min())


def measure_snapshot(vertices, poses, qpos, ids, links, faces=None):
    points = np.asarray(vertices)[ids]
    def distance(name):
        pose = poses[links[name]]
        if faces is None:
            return float(pad_face_distances(points, pose).min())
        return patch_pad_distance(vertices, faces, ids, pose)
    return {
        'material_hand_local_m': local_points(points, poses[links['hand']]).tolist(),
        'material_height_m': float(np.mean(points[:, 2])),
        'left_pad_distance_m': distance('left_finger'),
        'right_pad_distance_m': distance('right_finger'),
        'finger_gap_m': float(np.asarray(qpos)[7:].sum()),
    }


def observe(controller, ids):
    s = controller.scene.snapshot()
    return dict(tick=int(s['tick']), **measure_snapshot(
        s['cloth_vertices'], s['link_poses'][0], s['qpos'][0], ids,
        controller.scene.contact_link_indices, controller.scene.topology['faces']))


def hold_result(rows, baseline_height, cfg):
    if not rows:
        return {}, {'hold_recorded': False}
    p = cfg['contact_grasp']
    local = np.asarray([r['material_hand_local_m'] for r in rows])
    slip = float(np.linalg.norm(local - local[0], axis=-1).max())
    lift = min(r['material_height_m'] for r in rows) - baseline_height
    left = max(r['left_pad_distance_m'] for r in rows)
    right = max(r['right_pad_distance_m'] for r in rows)
    gaps = [r['finger_gap_m'] for r in rows]
    duration = (rows[-1]['tick'] - rows[0]['tick']) * cfg['dt']
    metrics = dict(minimum_lift_m=float(lift), maximum_material_slip_m=slip,
                   maximum_left_pad_distance_m=left, maximum_right_pad_distance_m=right,
                   minimum_gap_m=min(gaps), maximum_gap_m=max(gaps), hold_duration_s=duration)
    gates = dict(hold_recorded=duration >= p['hold_s'] - 1e-8,
                 physical_lift=lift >= p['minimum_lift_m'],
                 material_retained=slip <= p['maximum_material_slip_m'],
                 both_pads_near_material=max(left, right) <= p['maximum_pad_distance_m'],
                 loaded_gap=p['minimum_loaded_gap_m'] <= min(gaps)
                 and max(gaps) <= p['maximum_loaded_gap_m'])
    return metrics, {k: bool(v) for k, v in gates.items()}


def approach_geometry(vertices, faces, ids, cfg, default_rotation):
    """Align closing axis with a hanging sheet; preserve support clearance."""
    vertices = np.asarray(vertices)
    point = vertices[ids].mean(0)
    tri = np.asarray(faces, int)
    selected = tri[np.isin(tri, ids).any(axis=1)]
    normal = np.zeros(3)
    if len(selected):
        xyz = vertices[selected]
        normal = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]).sum(0)
        if np.linalg.norm(normal) > 1e-12:
            normal /= np.linalg.norm(normal)
    rotation = default_rotation
    if np.linalg.norm(normal[:2]) > .5:
        closing = np.r_[normal[:2] / np.linalg.norm(normal[:2]), 0.]
        # Choose the equivalent sign closest to the old wrist orientation.
        if closing @ default_rotation.as_matrix()[:, 1] < 0:
            closing *= -1
        forward = np.array([0., 0., -1.])
        rotation = Rotation.from_matrix(np.column_stack([np.cross(closing, forward), closing, forward]))
    goal = point - rotation.apply([0., 0., -.0005])
    support = None
    for table in cfg.get('tables', [cfg['table']]):
        center = np.asarray(table['position']); half = np.asarray(table['half_extents'])
        if np.all(np.abs(point[:2] - center[:2]) <= half[:2]):
            support = max(support if support is not None else -np.inf, center[2] + half[2])
    fixture = cfg.get('task_spec', {}).get('fixture', {})
    if fixture.get('kind') in ('basket', 'box'):
        w, d, h = fixture['size_m']; cx, cy = fixture['center_xy']
        if abs(point[0] - cx) < w / 2 and abs(point[1] - cy) < d / 2:
            top = fixture['base_height_m'] + (h if fixture['kind'] == 'box' else fixture['wall_m'])
            if point[2] >= top - .006:
                support = max(support if support is not None else -np.inf, top)
    if support is not None:
        goal[2] = max(goal[2], support + cfg['contact_grasp']['support_clearance_m'])
    return goal, rotation, {'surface_normal': normal.tolist(), 'support_height_m': support}


def acquire(c, ids, kind='single_layer', probe=False):
    from l_table_task import move_to
    from safety import Halted
    ids = list(map(int, ids))
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('Grasp needs distinct material indices')
    c.rec.phase = 'contact_approach'
    c.motion({'gripper': 'open'}, c.robot, c.rec, c.planner, gripper_width=.035)
    point = c.scene.cloth_vertices()[ids].mean(0)
    hover = point.copy(); hover[2] = max(point[2] + .10, c.cfg['table_height'] + .12)
    if hasattr(c, 'approach_height'):
        hover[2] = max(hover[2], c.approach_height(point))
    c.move(hover)
    goal, rotation, geometry = approach_geometry(
        c.scene.cloth_vertices(), c.scene.topology['faces'], ids, c.cfg, c.rotation)
    c.rec.mark('contact_grasp_target', vertex_ids=ids, goal=goal.tolist(),
               quaternion_wxyz=rotation.as_quat()[[3, 0, 1, 2]].tolist(), **geometry)
    move_to(c.robot, c.rec, c.planner, goal, rotation)
    c.rotation = rotation
    before = observe(c, ids)
    c.rec.phase = 'contact_close'
    c.rec.mark('contact_before_close', vertex_ids=ids, pinch_kind=kind, **before)
    closing = .035 if c.cfg['negative_control'] else c.cfg['contact_grasp']['closed_finger_target_m']
    c.motion({'gripper': 'keep'}, c.robot, c.rec, c.planner, gripper_width=closing)
    c.rec.mark('contact_after_close', vertex_ids=ids)
    c.rec.phase = 'contact_trial_lift'
    target = np.asarray(c.robot.state()[0]['position']) + [0., 0., c.cfg['contact_grasp']['probe_lift_m']]
    move_to(c.robot, c.rec, c.planner, target, rotation)
    c.rec.phase = 'contact_trial_hold'
    c.rec.mark('contact_hold_start', vertex_ids=ids)
    rows = [observe(c, ids)]
    stride = c.cfg['record_stride']
    for i in range(round(c.cfg['contact_grasp']['hold_s'] / c.cfg['dt'])):
        c.robot.tick(record=c.rec)
        if (i + 1) % stride == 0:
            rows.append(observe(c, ids))
    metrics, gates = hold_result(rows, before['material_height_m'], c.cfg)
    c.rec.mark('contact_hold_end', vertex_ids=ids, pinch_kind=kind, metrics=metrics, gates=gates)
    if all(gates.values()) and not c.cfg['negative_control']:
        c.rec.mark('contact_grasp_verified', vertex_ids=ids, pinch_kind=kind)
        c.mark('acquired', vertex_index=ids[0], vertex_ids=ids, pinch_kind=kind)
    elif not probe:
        c.rec.mark('contact_grasp_failed', vertex_ids=ids, gates=gates)
        raise Halted('Physical acquisition failed: ' + ', '.join(k for k, v in gates.items() if not v))
    return metrics, gates


def release(c):
    """Bounded feedback opening, retaining the original 5 N motor limits."""
    from safety import Halted
    c.rec.phase = 'contact_release'
    c.rec.mark('contact_before_release')
    arm = c.robot.targets[0][:7].copy(); command = c.robot.targets[0][7:].copy()
    dt = c.cfg['dt']; stable = 0
    for _ in range(round(8. / dt)):
        measured = np.asarray(c.robot.state()[0]['fingers'])
        command = np.maximum(command, np.minimum(np.minimum(command + .025 * dt, measured + .001), .035))
        state = c.robot.tick([np.r_[arm, command]], record=c.rec)[0]
        settled = np.max(np.abs(np.asarray(state['fingers']) - .035)) < .0005
        stable = stable + 1 if settled else 0
        if stable >= round(.1 / dt):
            break
    else:
        raise Halted('Physical opening remained obstructed after 8 seconds')
    c.rec.mark('contact_grasp_released')
    c.hold(c.robot, c.rec, .6)


def run_probe(robot, rec, planner):
    from tabletop_v2.actions import Controller
    c = Controller(robot, rec, planner)
    index = c.cfg.get('probe_vertex')
    if index is None:
        index = c.cfg.get('scene_grasp_seed', {}).get('vertex_index', c.cfg['task_spec']['primary_corner'])
    acquire(c, [int(index)], probe=True)
    release(c)
    c.hold(robot, rec, 1.)
    rec.mark('contact_probe_complete')


def evaluate_contact(data, events, cfg, audit, topology=None):
    """Recompute controller claims from saved vertices and link poses."""
    links = audit['contact_link_indices']
    ticks = np.asarray(data['tick'])
    pending = None; start = None; trials = []
    for event in events:
        if event['name'] == 'contact_before_close':
            pending = event; start = None
        elif event['name'] == 'contact_hold_start':
            start = event
        elif event['name'] == 'contact_hold_end' and pending is not None and start is not None:
            baseline_ix = np.flatnonzero(ticks == pending['tick'])
            if len(baseline_ix) != 1:
                raise ValueError('Missing exact pre-close snapshot')
            ids = pending['vertex_ids']
            rows = []
            for i in np.flatnonzero((ticks >= start['tick']) & (ticks <= event['tick'])):
                rows.append(dict(tick=int(ticks[i]), **measure_snapshot(
                    data['cloth_vertices'][i], data['link_poses'][i, 0], data['qpos'][i, 0], ids, links,
                    topology['faces'] if topology is not None else None)))
            height = float(np.mean(data['cloth_vertices'][baseline_ix[0], ids, 2]))
            metrics, gates = hold_result(rows, height, cfg)
            trials.append(dict(vertex_ids=ids, metrics=metrics, gates=gates))
            pending = None; start = None
    constraints = data.get('cloth_constrained_vertices') if isinstance(data, dict) else (
        data['cloth_constrained_vertices'] if 'cloth_constrained_vertices' in data.files else None)
    released = [e for e in events if e['name'] == 'contact_grasp_released']
    release_ix = np.flatnonzero(ticks >= released[-1]['tick']) if released else []
    release_valid = bool(len(release_ix) and np.all(data['qpos'][release_ix, 0, 7:] >= .034)
                         and (ticks[-1] - ticks[release_ix[0]]) * cfg['dt'] >= .5)
    gates = dict(no_cloth_constraints=constraints is not None and bool(np.all(constraints == 0))
                 and not cfg['assisted_grasp']['enabled'],
                 physical_acquisitions_verified=bool(trials) and all(all(t['gates'].values()) for t in trials),
                 contact_release_verified=release_valid)
    # A proximity observation cannot turn the open-jaw control into success.
    gates['closed_gripper_trial'] = not cfg['negative_control']
    return {'contact_trials': trials}, gates
