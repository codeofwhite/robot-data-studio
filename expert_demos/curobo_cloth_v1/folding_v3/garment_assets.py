"""Explicit triangle topology and material labels for the local DiffCloth T-shirt."""
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

SOURCE = Path('/data/zhanghejun/DiffCloth/src/assets/meshes/remeshed/T-shirt/tshirt1900-flattened.obj')

def read_obj(path):
    vertices, faces = [], []
    for line in Path(path).read_text().splitlines():
        if line.startswith('v '): vertices.append(list(map(float, line.split()[1:4])))
        elif line.startswith('f '):
            face = [int(x.split('/')[0]) - 1 for x in line.split()[1:]]
            if len(face) != 3: raise ValueError('Garment source must contain triangles')
            faces.append(face)
    return np.asarray(vertices), np.asarray(faces, dtype=int)

def boundary_loops(faces):
    counts = Counter(tuple(sorted((int(a), int(b)))) for f in faces for a, b in zip(f, np.roll(f, -1)))
    if max(counts.values()) > 2: raise ValueError('Nonmanifold garment edge')
    # Preserve directed face winding; cap faces later use the opposite direction.
    outgoing = {}
    for f in faces:
        for a, b in zip(f, np.roll(f, -1)):
            if counts[tuple(sorted((int(a), int(b))))] == 1:
                if int(a) in outgoing: raise ValueError('Nonmanifold boundary')
                outgoing[int(a)] = int(b)
    remaining, loops = set(outgoing), []
    while remaining:
        start = min(remaining); loop = [start]; remaining.remove(start); nxt = outgoing[start]
        while nxt != start:
            if nxt not in remaining: raise ValueError('Inconsistent boundary winding')
            remaining.remove(nxt); loop.append(nxt); nxt = outgoing[nxt]
        loops.append(loop)
    return loops

def signed_capped_volume(vertices, faces, loops):
    """A rotation-invariant orientation diagnostic, not a standalone eversion test."""
    v = np.asarray(vertices, float); v = v - v.mean(0)
    tri = v[np.asarray(faces)]
    volume = np.einsum('ij,ij->i', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6
    for loop in loops:
        p = v[loop]; center = p.mean(0)
        volume += np.einsum('ij,ij->i', np.roll(p, -1, axis=0), np.cross(p, center)).sum() / 6
    return float(volume)

def prepare_garment(cfg):
    source, faces = read_obj(SOURCE)
    # Proper rotation from the source's Y-up flattened mesh: no winding changes.
    local = source[:, [0, 2, 1]] * [1, 1, -1]
    local *= .36 / np.ptp(local[:, 1])
    local[:, :2] -= (local[:, :2].max(0) + local[:, :2].min(0)) / 2
    local[:, 2] -= local[:, 2].min()
    repair = None
    if cfg.get('reference_repair'):
        if cfg['reference_repair'] not in ('right_cuff_laplacian_v1','right_cuff_laplacian_v2'): raise ValueError('Unknown reference repair')
        # The imported flattened cuff has an edge/triangle self-intersection.
        # Repair only its one-ring neighborhood, before defining the stress-free
        # reference. This is asset authoring, never a runtime cloth correction.
        neighbors = [set() for _ in local]
        for face in faces:
            for a, b in zip(face, np.roll(face, -1)):
                neighbors[a].add(int(b)); neighbors[b].add(int(a))
        seeds = {82, 414, 302, 83, 274}
        selected = sorted(seeds | set().union(*(neighbors[i] for i in seeds)))
        original = local.copy()
        for _ in range(3):
            local[selected] += .35 * (np.array([local[sorted(neighbors[i])].mean(0) for i in selected]) - local[selected])
        edge_length = None
        if cfg['reference_repair'] == 'right_cuff_laplacian_v2':
            # Smoothing alone leaves this interior edge shorter than the contact
            # thickness plus barrier region. Its first step stretched by 33%.
            # Author a 3 mm reference edge symmetrically, keeping all connectivity.
            midpoint = (local[82]+local[83])/2
            direction = local[82]-local[83]; direction /= np.linalg.norm(direction)
            edge_length = .003
            local[82] = midpoint+direction*edge_length/2; local[83] = midpoint-direction*edge_length/2
        repair = dict(method='three Jacobi Laplacian steps, alpha 0.35, defective right-cuff one-ring only',
            vertex_ids=selected, max_displacement_m=float(np.linalg.norm(local-original,axis=1).max()),
            regularized_edge=[82,83] if edge_length else None, regularized_edge_length_m=edge_length,
            source_reference_changed=True, topology_preserved=True,
            validation='IPC self-intersection and 1.2 mm pair-thickness checks; unchanged contact model')
    loops = boundary_loops(faces)
    if len(loops) != 4: raise ValueError('Expected neck, hem and two cuff openings')
    centers = np.array([local[x].mean(0) for x in loops])
    hem = int(np.argmin(centers[:, 1])); neck = int(np.argmax(centers[:, 1]))
    cuffs = sorted((i for i in range(4) if i not in (hem, neck)), key=lambda i: centers[i, 0])
    openings = dict(hem=loops[hem], neck=loops[neck], left_cuff=loops[cuffs[0]], right_cuff=loops[cuffs[1]])
    tri = local[faces]; normal = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
    front = np.flatnonzero(normal[:, 2] > .35 * np.linalg.norm(normal, axis=1))
    back = np.flatnonzero(normal[:, 2] < -.35 * np.linalg.norm(normal, axis=1))
    # Anatomical panels stay attached to material indices across every motion.
    centroid = tri.mean(1)
    panels = dict(body=np.flatnonzero(abs(centroid[:, 0]) < .075).tolist(),
                  left_sleeve=np.flatnonzero(centroid[:, 0] < -.09).tolist(),
                  right_sleeve=np.flatnonzero(centroid[:, 0] > .09).tolist())
    keypoints = {}
    for name, ids in openings.items():
        ids = np.array(ids)
        keypoints[name+'_upper'] = int(ids[np.argmax(local[ids, 2])])
        keypoints[name+'_lower'] = int(ids[np.argmin(local[ids, 2])])
    hem_ids = np.array(openings['hem'])
    for side, sign in [('left', -1), ('right', 1)]:
        score = sign*local[hem_ids, 0] + .3*local[hem_ids, 2]
        keypoints[side+'_hem'] = int(hem_ids[np.argmax(score)])
    rest_local = local.copy()
    if cfg.get('inside_out'):
        # An authored inverted initial embedding: reflect only the thickness axis.
        # Connectivity/material orientation are preserved, so capped volume changes
        # sign. This is initialization only, never an executed eversion trajectory.
        local[:, 2] = local[:, 2].max() - local[:, 2]
    rot = Rotation.from_euler('z', cfg['yaw_deg'], degrees=True)
    offset = np.r_[cfg['center'], .784]
    current = rot.apply(local) + offset
    rest = rot.apply(rest_local) + offset
    edges = np.asarray(sorted({tuple(sorted((int(a), int(b)))) for f in faces for a, b in zip(f, np.roll(f, -1))}))
    ratio = np.linalg.norm(current[edges[:, 0]]-current[edges[:, 1]], axis=1)/np.linalg.norm(rest[edges[:, 0]]-rest[edges[:, 1]], axis=1)
    n = len(current); uv = (rest_local[:, :2]-rest_local[:, :2].min(0))/np.ptp(rest_local[:, :2], axis=0)
    topology = dict(rest_vertices=rest.tolist(), initial_vertices=current.tolist(), faces=faces.tolist(), edges=edges.tolist(),
        flat_area_m2=float(np.linalg.norm(normal, axis=1).sum()/2), rest_shape='authored flattened sewn T-shirt; nonplanar reference mesh',
        initial_max_edge_ratio=float(ratio.max()), source_vertex_ids=list(range(n)), source_vertex_count=n,
        visual_indices=[[i,i,i] for i in range(n)], visual_weights=[[1.,0.,0.] for _ in range(n)], visual_uv=uv.tolist(),
        material_size_m=np.ptp(rest_local[:, :2], axis=0).tolist(), garment=dict(openings=openings, panels=panels,
        front_faces=front.tolist(), back_faces=back.tolist(), keypoints=keypoints,
        reference_capped_volume_m3=signed_capped_volume(rest,faces,loops),
        initial_embedding='thickness-reflected inside-out' if cfg.get('inside_out') else 'original outward embedding',
        source=str(SOURCE), source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        reference_geometry_repair=repair))
    return current, faces, topology

def load_mapping(stage, entry):
    """Read the explicit topology embedded in this scene's immutable sidecar."""
    import json
    from pxr import UsdGeom
    from scene_adapter import ASSETS
    topology = json.loads((ASSETS/entry['topology_asset']).read_text())
    points = np.asarray(UsdGeom.Mesh(stage.GetPrimAtPath(entry['prim'])).GetPointsAttr().Get(), float)
    if not np.allclose(points, topology['initial_vertices'], atol=1e-7): raise ValueError('Garment mesh/topology mismatch')
    topology['source_prim'] = entry['prim']
    return topology
