"""Single-arm Genesis IPC physics, with a persistent Isaac RTX display process."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent
STUDIO = CORE.parents[1]



def prepare_rigid_ipc(world, robot):
    """Use the same Panda adjacent-body exclusions with an actual rigid object set."""
    from genesis.engine.couplers.ipc_coupler.utils import find_target_link_for_fixed_merge
    from safety import approved_adjacent_pairs
    import uipc
    coupler = world.sim.coupler
    original = coupler._register_contact_pairs
    audit = {}
    def register():
        original()
        if coupler.rigid_solver._enable_adjacent_collision:
            raise ValueError('Expected native adjacent collision filtering')
        merged = {find_target_link_for_fixed_merge(link) for link in robot.links if link.geoms}
        expected = {'link'+str(i) for i in range(8)} | {'left_finger', 'right_finger'}
        if {link.name for link in merged} != expected:
            raise ValueError('Unexpected Panda collision bodies')
        original_element = coupler._ipc_abd_contacts[robot]
        elements = {}
        for link in sorted(merged, key=lambda link: link.idx):
            element = coupler._ipc_contact_tabular.create('rigid_adjacent_' + link.name)
            for slot in coupler._abd_slots_by_link[link]:
                element.apply_to(slot.geometry())
            elements['arm/' + link.name] = element
        allowed = approved_adjacent_pairs(['arm'])
        source = coupler._ipc_contact_tabular.at(original_element.id(), original_element.id())
        for a, x in elements.items():
            for b, y in elements.items():
                key = '|'.join(sorted([a, b]))
                coupler._ipc_contact_tabular.insert(x, y, source.friction_rate(),
                    source.resistance(), key not in allowed, source.config())
            coupler._ipc_contact_tabular.insert(coupler._ipc_no_collision_contact, x, 0., 0., False)
        # Cross contacts inherit the original articulated-robot material exactly.
        for entity, other in coupler._ipc_abd_contacts.items():
            if entity is robot:
                continue
            reference = coupler._ipc_contact_tabular.at(original_element.id(), other.id())
            for element in elements.values():
                coupler._ipc_contact_tabular.insert(element, other, reference.friction_rate(),
                    reference.resistance(), reference.is_enabled(), reference.config())
        audit.update(excluded_pairs=sorted(allowed), fixed_object='cube',
                     robot_bodies=sorted(elements), cross_contact_policy='inherit original IPC table')
    coupler._register_contact_pairs = register
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--garment-dir', type=Path)
    parser.add_argument('--rigid-only', action='store_true')
    parser.add_argument('--parameters', type=json.loads, default={})
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--isaac-python', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--episode-root', type=Path)
    parser.add_argument('--control-fps', type=int, default=10)
    parser.add_argument('--target-episodes', type=int, default=0)
    parser.add_argument('--collector-ui-root', type=Path, default=STUDIO.parent / 'gello-remote/src/gello_remote/web/genesis')
    parser.add_argument('--max-steps', type=int, default=0, help='bounded native smoke; 0 runs until stopped')
    args = parser.parse_args()
    if not 1 <= args.control_fps <= 60:
        parser.error('control-fps must be between 1 and 60')
    output = args.output.resolve()
    args.episode_root = (args.episode_root or output / 'episodes').resolve()
    output.mkdir(parents=True, exist_ok=True)
    for key in ('GS_CACHE_FILE_PATH', 'XDG_CACHE_HOME', 'MPLCONFIGDIR'):
        if os.environ.get(key):
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
    # Reuse the expert runtime's per-instance IPC compatibility and contact setup.
    sys.path[:0] = [str(CORE / 'runtime'), str(STUDIO.parent / 'ClothForge/src'), str(STUDIO / 'packages/robot-data-contracts/src')]
    import numpy as np
    from scipy.spatial.transform import Rotation
    import genesis as gs
    from scene import Scene
    from ipc_axis_compat import install_axis_compat
    from ipc_state_sync import install_state_sync
    from garment_ipc import prepare, install
    from collector import run

    cfg = json.loads((CORE / 'runtime/base_config.json').read_text())
    params = args.parameters
    cfg['dt'] = 1 / (args.control_fps * max(1, round(1 / (args.control_fps * cfg['dt']))))
    if not args.rigid_only and args.garment_dir is None:
        parser.error('--garment-dir is required for the cloth scene')
    garment = None if args.rigid_only else prepare(args.garment_dir, params, cfg['table_height'])
    if garment is not None:
        vertices, faces = garment['vertices'], garment['faces']
        material, mapping = garment['material'], garment['mapping']
        assembly = output / 'assembly.obj'
        assembly.write_text('\n'.join(['v ' + ' '.join(map(str, v)) for v in vertices] +
                                      ['f ' + ' '.join(map(str, f + 1)) for f in faces]) + '\n')
    else:
        material = {'friction': .6}
    # Bake the same expert Panda reference pose into an output-local MJCF.
    import xml.etree.ElementTree as ET
    panda_source = Path(cfg['source_project']) / 'assets/panda.xml'
    tree = ET.parse(panda_source)
    tree.getroot().find('compiler').set('meshdir', str(panda_source.parent / 'meshes'))
    names = ['joint' + str(i) for i in range(1, 8)] + ['finger_joint1', 'finger_joint2']
    for name, target in zip(names, cfg['home']):
        body = next(b for b in tree.findall('.//body') if b.find('joint') is not None and b.find('joint').get('name') == name)
        joint = body.find('joint')
        delta = target - float(joint.get('ref', '0'))
        quat = np.array(list(map(float, body.get('quat', '1 0 0 0').split())))
        rot = Rotation.from_quat(quat[[1, 2, 3, 0]])
        axis = np.array(list(map(float, joint.get('axis', '0 1 0' if name.startswith('finger') else '0 0 1').split())))
        if name.startswith('finger'):
            pos = np.array(list(map(float, body.get('pos', '0 0 0').split()))) + rot.apply(axis * delta)
            body.set('pos', ' '.join(map(str, pos)))
        else:
            body.set('quat', ' '.join(map(str, (rot * Rotation.from_rotvec(axis * delta)).as_quat()[[3, 0, 1, 2]])))
        joint.set('ref', str(target))
    tree.write(output / 'panda.xml', encoding='unicode')

    gs.init(backend=gs.gpu, precision='32', seed=cfg['seed'], logging_level='warning')

    class LiveScene:
        adjacent_contact_configuration = Scene.adjacent_contact_configuration
        def rigid_objects(self):
            return {'floor': self.floor, 'table': self.table, **({'cube': self.cube} if hasattr(self, 'cube') else {})}

    live = LiveScene()
    live.cfg = cfg
    world = live.world = gs.Scene(
        sim_options=gs.options.SimOptions(dt=cfg['dt'], substeps=1),
        rigid_options=gs.options.RigidOptions(iterations=100, tolerance=1e-8,
            constraint_timeconst=max(.008, 2 * cfg['dt']), enable_self_collision=True, enable_neutral_collision=True),
        coupler_options=gs.options.IPCCouplerOptions(two_way_coupling=True, enable_rigid_rigid_contact=True,
            enable_rigid_ground_contact=False, enable_rigid_dofs_sync=True,
            newton_semi_implicit_enable=False, contact_d_hat=cfg['ipc']['d_hat'],
            newton_tolerance=cfg['ipc']['newton_tolerance'], contact_friction_enable=True,
            linesearch_report_energy=False), show_viewer=False)
    coupler = world.sim.coupler
    axis_audit = install_axis_compat(coupler)
    def rigid():
        return gs.materials.Rigid(coup_type='ipc_only', coup_friction=material['friction'])
    live.floor = world.add_entity(gs.morphs.Box(pos=(0, 0, -.05), size=(4, 4, .1), fixed=True), material=rigid())
    live.table = world.add_entity(gs.morphs.Box(pos=cfg['table']['position'],
        size=(2 * np.asarray(cfg['table']['half_extents'])).tolist(), fixed=True), material=rigid())
    robot = world.add_entity(gs.morphs.MJCF(file=str(output / 'panda.xml'), pos=cfg['bases'][0]),
        material=gs.materials.Rigid(coup_type='external_articulation', coup_friction=.8))
    for name, value in zip(names, cfg['home']):
        robot.get_joint(name).init_qpos[:] = value
    live.robots = [robot]
    if args.rigid_only:
        cube = live.cube = world.add_entity(gs.morphs.Box(pos=(-.12, -.08, cfg['table_height'] + .041),
            size=(.08, .08, .08), fixed=True), material=rigid())
        native = None
    else:
        live.cloth = world.add_entity(gs.morphs.Mesh(file=str(assembly), convexify=False, decimate=False),
            material=gs.materials.FEM.Cloth(E=mapping['young_pa'], nu=mapping['poisson'],
                rho=mapping['density_kg_m3'], thickness=mapping['thickness_m'],
                bending_stiffness=mapping['bending_stiffness'], friction_mu=mapping['friction']))
        native = install(coupler, garment)
    if args.rigid_only:
        axis_audit['rigid_contacts'] = prepare_rigid_ipc(world, robot)
    else:
        Scene.prepare_adjacent_ipc(live)
    world.build()
    sync_audit = install_state_sync(coupler, [robot], cfg['dt'])
    robot.set_dofs_kp(np.array(cfg['kp']))
    robot.set_dofs_kv(np.array(cfg['kv']))
    caps = np.r_[cfg['arm_force_limits'], cfg['finger_force_limit'], cfg['finger_force_limit']]
    robot.set_dofs_force_range(-caps, caps)
    run(args, cfg, world, robot, native, garment, output, axis_audit, sync_audit,
        cube=cube if args.rigid_only else None)


if __name__ == '__main__':
    main()
