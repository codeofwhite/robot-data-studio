"""Version-pinned, per-scene IPC revolute-axis compatibility adapter.

This changes only the revolute axis vertex ordering in the installed construction
method. Prismatic joints, control targets, forces and contact settings are unchanged.
The shared Genesis files and IPCCoupler class are never modified.
"""
import hashlib
import inspect
import textwrap
import types
from pathlib import Path
from importlib.metadata import version

EXPECTED_VERSIONS = {'genesis-world': '1.3.1', 'pyuipc': '0.0.25'}
EXPECTED_SOURCE_SHA256 = '3abb92935d34ed83b98cc87e65e0167b289233461dc7d9d9a72dcc46a55f483a'
EXPECTED_METHOD_SHA256 = 'e2c791a827a9c236eedf8568d51afd4c496bb0366294fcd70799ff36c375cb60'
METHOD = '_add_articulation_entities_to_ipc'

def install_axis_compat(coupler):
    from genesis.engine.couplers.ipc_coupler.coupler import IPCCoupler
    if type(coupler) is not IPCCoupler:
        raise TypeError('Axis adapter requires the audited IPCCoupler implementation')
    if METHOD in coupler.__dict__:
        raise RuntimeError('Construction method already overridden on this scene')
    installed = {name: version(name) for name in EXPECTED_VERSIONS}
    if installed != EXPECTED_VERSIONS:
        raise RuntimeError(f'Unaudited runtime versions: {installed}')
    original = getattr(IPCCoupler, METHOD)
    source_file = Path(inspect.getsourcefile(original))
    if hashlib.sha256(source_file.read_bytes()).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise RuntimeError('Shared IPC source differs from the audited version')
    source = textwrap.dedent(inspect.getsource(original)).strip()
    if hashlib.sha256(source.encode()).hexdigest() != EXPECTED_METHOD_SHA256:
        raise RuntimeError('IPC articulation constructor differs from audited source')
    if source.count('reverse_verts = True') != 1:
        raise RuntimeError('Expected exactly one revolute-axis reversal')
    revised = source.replace('reverse_verts = True', 'reverse_verts = False')
    namespace = dict(original.__globals__)
    exec(compile(revised, __file__ + ':audited_constructor', 'exec'), namespace)
    replacement = namespace[METHOD]
    setattr(coupler, METHOD, types.MethodType(replacement, coupler))
    if getattr(IPCCoupler, METHOD) is not original:
        raise RuntimeError('Unexpected modification to shared coupler class')
    return {'scope': 'this coupler instance only', 'versions': installed,
            'original_method_sha256': EXPECTED_METHOD_SHA256,
            'patched_method_sha256': hashlib.sha256(revised.encode()).hexdigest(),
            'change': 'Revolute axis uses [v1,v2]; prismatic ordering unchanged'}
