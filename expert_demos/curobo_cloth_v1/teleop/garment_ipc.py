"""ClothForge input and IPC rest geometry, shared by collection and import smoke."""
from pathlib import Path
import json
import numpy as np
from scipy.sparse import coo_matrix
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares


def edge_metric(faces, rest):
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [0, 2]], faces[:, [1, 2]]])
    lengths = np.concatenate([np.linalg.norm(rest[:, i] - rest[:, j], axis=1)
                              for i, j in [(0, 1), (0, 2), (1, 2)]])
    edges = np.sort(edges, axis=1)
    unique, inverse = np.unique(edges, axis=0, return_inverse=True)
    sums = np.bincount(inverse, weights=lengths)
    target = sums / np.bincount(inverse)
    if np.max(abs(lengths - target[inverse])) > 1e-9:
        raise ValueError('Per-face rest lengths disagree at a shared edge')
    return unique, target


def fit_rest(vertices, faces, rest):
    """Recover an assembled reference from rest edge lengths, never from posed strain."""
    edges, lengths = edge_metric(faces, rest)
    n = len(vertices)
    rows = np.repeat(np.arange(len(edges)), 6)
    columns = (edges[:, :, None] * 3 + np.arange(3)).reshape(-1)
    def residual(x):
        p = x.reshape(n, 3)
        return (np.linalg.norm(p[edges[:, 1]] - p[edges[:, 0]], axis=1) - lengths) / lengths
    def jacobian(x):
        p = x.reshape(n, 3)
        delta = p[edges[:, 1]] - p[edges[:, 0]]
        norm = np.linalg.norm(delta, axis=1)
        if np.any(norm < 1e-14):
            raise ValueError('Collapsed edge during rest reconstruction')
        gradient = delta / (norm * lengths)[:, None]
        values = np.stack([-gradient, gradient], axis=1).reshape(-1)
        return coo_matrix((values, (rows, columns)), shape=(len(edges), 3 * n)).tocsr()
    result = least_squares(residual, vertices.ravel(), jac=jacobian, tr_solver='lsmr',
        max_nfev=100, ftol=1e-13, xtol=1e-13, gtol=1e-11,
        tr_options={'atol': 1e-11, 'btol': 1e-11, 'maxiter': 200})
    error = float(abs(residual(result.x)).max())
    if error > 1e-5:
        raise ValueError(f'Rest metric reconstruction did not converge: relative edge error={error:g}')
    return result.x.reshape(n, 3), {'rest_strategy': 'reconstructed_3d_metric',
        'max_relative_rest_edge_error': error, 'solver_evaluations': result.nfev,
        'bending_reference': 'reconstructed assembled rest shape; free seam hinges'}


def prepare(directory, params, table_height):
    from clothforge.comparison import ipc_material
    from clothforge.schema import digest, validate_material
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if digest(directory / 'mesh.npz') != manifest['mesh_sha256']:
        raise ValueError('ClothForge mesh differs from its manifest')
    preset = params.get('material_preset', 'medium')
    config = json.loads((directory / f'config-{preset}.json').read_text())
    material = {**config['material'], **{k: params[k] for k in
                ('mass_per_area', 'friction', 'tri_ke', 'tri_ka', 'edge_ke') if k in params}}
    validate_material(material)
    with np.load(directory / 'mesh.npz', allow_pickle=False) as mesh:
        vertices = mesh['vertices'].copy()
        faces = mesh['faces'].copy()
        rest = mesh['rest_triangles'].copy()
        seams = {tuple(e) for e in mesh['seam_edges'].tolist()}
    scale = float(params.get('garment_scale', 1))
    vertices *= scale
    rest *= scale
    flat = np.column_stack([vertices[:, 0], np.zeros(len(vertices)), vertices[:, 2]])
    expected = np.linalg.norm(rest[:, :, None] - rest[:, None, :], axis=-1)
    actual = np.linalg.norm(flat[faces][:, :, None] - flat[faces][:, None, :], axis=-1)
    if np.allclose(expected, actual, atol=1e-9):
        reference = flat
        audit = {'rest_strategy': 'planar_pattern', 'max_relative_rest_edge_error': 0.,
                 'bending_reference': 'flat panels; free seam hinges'}
        vertices -= (vertices.min(0) + vertices.max(0)) / 2
        vertices = np.column_stack([vertices[:, 0], vertices[:, 2], -vertices[:, 1]])
    else:
        reference, audit = fit_rest(vertices, faces, rest)
        vertices[:, :2] -= (vertices[:, :2].min(0) + vertices[:, :2].max(0)) / 2
    vertices = Rotation.from_euler('z', float(params.get('garment_rotation_deg', 0)), degrees=True).apply(vertices)
    vertices += [-.12 + float(params.get('garment_offset_x_m', 0)),
                 -.08 + float(params.get('garment_offset_y_m', 0)),
                 table_height + .006 - vertices[:, 2].min()]
    return dict(vertices=vertices, reference=reference, faces=faces, rest=rest, seams=seams,
                material=material, mapping=ipc_material(material), manifest=manifest, audit=audit)


def install(coupler, garment, object_name="cloth_0_0"):
    import uipc
    from clothforge.quality import rest_matrices
    native = {}
    original = coupler._add_fem_entities_to_ipc
    vertices, faces, mapping = garment['vertices'], garment['faces'], garment['mapping']
    def configure():
        original()
        obj, = coupler._ipc_objects.find(object_name)
        current, reference = coupler._ipc_scene.geometries().find(int(list(obj.geometries().ids())[0]))
        cg, rg = current.geometry(), reference.geometry()
        loaded = np.asarray(rg.positions().view()).reshape(-1, 3)
        distance, order = cKDTree(loaded).query(vertices)
        if len(loaded) != len(vertices) or len(set(order)) != len(vertices) or distance.max() > 1e-7:
            raise ValueError(f'IPC changed garment vertices for {object_name}: input={len(vertices)}, loaded={len(loaded)}, matched={len(set(order))}, max_distance={distance.max():g}')
        inverse = np.argsort(order)
        native_faces = np.asarray(rg.triangles().topo().view()).reshape(-1, 3)
        if sorted(map(tuple, np.sort(inverse[native_faces], axis=1))) != sorted(map(tuple, np.sort(faces, axis=1))):
            raise ValueError('IPC changed garment topology')
        uipc.view(rg.positions()).reshape(-1, 3)[order] = garment['reference']
        uipc.view(cg.positions()).reshape(-1, 3)[order] = vertices
        _, areas = rest_matrices(garment['rest'])
        volume = np.bincount(faces.ravel(), weights=np.repeat(areas * 2 * mapping['thickness_m'] / 3, 3), minlength=len(vertices))
        for geom in (cg, rg):
            uipc.view(geom.vertices().find('volume')).reshape(-1)[order] = volume
            edges = np.asarray(geom.edges().topo().view()).reshape(-1, 2)
            bending = uipc.view(geom.edges().find('bending_stiffness')).reshape(-1)
            for i, edge in enumerate(inverse[edges]):
                if tuple(sorted(edge)) in garment['seams']:
                    bending[i] = 0
        native.update(geom=cg, order=order)
    coupler._add_fem_entities_to_ipc = configure
    return native


def positions(native):
    import uipc
    geom, = uipc.geometry.apply_transform(native['geom'])
    return np.asarray(geom.positions().view()).reshape(-1, 3)[native['order']].copy()
