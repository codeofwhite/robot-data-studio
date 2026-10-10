from pathlib import Path
import pytest
from robot_data_studio.adapters.isaac_sim import IsaacSimAdapter


def config(**updates):
    return dict(scene_id="bimanual_tabletop_v17", control_mode="keyboard", gpu=2,
                port=18082, control_fps=20, width=960, height=720, scene_params={},
                camera_profile_id="isaac_bimanual_tabletop_visual_v4",
                renderer_profile_id="isaac_balanced_v1", physics_backend="physx", **updates)


def test_live_bimanual_launch_reuses_v17_assets_without_visual_capture():
    command = IsaacSimAdapter().build_collect_command(config(), Path("/tmp/bimanual-test"))
    for flag, suffix in (("--workstation-usd", "bimanual_tabletop_lab_v17.usda"),
                         ("--workstation-manifest-file", "asset_manifest_bimanual_v17.json"),
                         ("--franka-usd", "assets/franka/franka.usd")):
        assert command[command.index(flag) + 1].endswith(suffix)
    assert command[command.index("--scene") + 1] == "bimanual_tabletop_v17"
    assert "--visual-demo-output" not in command
    assert command[command.index("--width") + 1] == "960"


@pytest.mark.parametrize("key,value", [("control_mode", "gello"), ("physics_backend", "newton"),
                                       ("camera_profile_id", "lab_d435i_dual_v1"), ("width", 640)])
def test_rejects_incompatible_bimanual_launch(key, value):
    candidate = config()
    candidate[key] = value
    with pytest.raises(ValueError):
        IsaacSimAdapter().validate_config(candidate)


@pytest.fixture
def clothforge_registry(tmp_path, monkeypatch):
    import json
    from robot_data_contracts.asset import AssetArtifact, AssetDraft
    from robot_data_studio.services.asset_service import AssetRegistry
    folder = tmp_path / 'garments' / 'tshirt-test'
    folder.mkdir(parents=True)
    (folder / 'mesh.npz').write_bytes(b'mesh fixture')
    (folder / 'manifest.json').write_text(json.dumps({'id': 'tshirt-test'}))
    for preset, density in [('light', .1), ('medium', .22), ('heavy', .4)]:
        (folder / f'config-{preset}.json').write_text(json.dumps({'material': {
            'mass_per_area': density, 'friction': .5, 'tri_ke': 3000, 'tri_ka': 3000, 'edge_ke': .005}}))
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps({'schema_version': 1, 'sources': {'fixture': {'root': str(tmp_path / 'garments')}}}))
    registry = AssetRegistry(tmp_path / 'registry', sources)
    registry.publish(AssetDraft(asset_id='MDL-clothforge-tshirt-test', kind='model', name='测试 T 恤', tags=['clothforge'],
        change_note='fixture', artifacts=[AssetArtifact(source_id='fixture', path='tshirt-test/'+name, role=role)
        for name, role in [('manifest.json', 'provenance'), ('mesh.npz', 'simulation_mesh')]]))
    monkeypatch.setattr('robot_data_studio.services.asset_service.AssetRegistry', lambda: registry)
    return registry, folder


def clothforge_config(params=None):
    c = config()
    c['scene_id'] = 'bimanual_tabletop_v17_clothforge'
    c['scene_params'] = {'garment_asset_id': 'MDL-clothforge-tshirt-test', **(params or {})}
    return c


def test_clothforge_selection_and_parameters_are_passed_to_existing_worker(clothforge_registry):
    import json
    registry, folder = clothforge_registry
    source = (folder / 'config-heavy.json').read_bytes()
    a = IsaacSimAdapter()
    command = a.build_collect_command(clothforge_config({'material_preset': 'heavy', 'friction': .8,
                                                       'garment_rotation_deg': 90}), Path('/tmp/clothforge-test'))
    params = json.loads(command[command.index('--clothforge-params') + 1])
    assert params['mass_per_area'] == .4
    assert params['friction'] == .8
    assert params['garment_rotation_deg'] == 90
    assert params['garment_version'] == 1
    assert command[command.index('--clothforge-dir') + 1] == str(folder)
    assert '--workstation-usd' in command and '--scene-usd' not in command
    assert (folder / 'config-heavy.json').read_bytes() == source
    choices = a.scene_descriptors()['bimanual_tabletop_v17_clothforge']['parameters'][0]['choices']
    assert choices == ['MDL-clothforge-tshirt-test']


@pytest.mark.parametrize('params', [{'friction': float('nan')}, {'garment_scale': -1},
                                    {'material_preset': '../medium'}, {'cloth_iterations': 4.5},
                                    {'garment_version': True}, {'unexpected': 1}])
def test_invalid_clothforge_parameters_fail_before_launch(clothforge_registry, params):
    with pytest.raises(ValueError):
        IsaacSimAdapter().build_collect_command(clothforge_config(params), Path('/tmp/clothforge-test'))


def test_newton_clothforge_uses_same_asset_and_parameter_contract(clothforge_registry):
    import json
    candidate = clothforge_config({'friction': .8, 'cloth_iterations': 12})
    candidate['physics_backend'] = 'newton'
    adapter = IsaacSimAdapter()
    adapter.validate_config(candidate)
    command = adapter.build_collect_command(candidate, Path('/tmp/clothforge-newton-test'))
    assert command[command.index('--physics-backend') + 1] == 'newton'
    params = json.loads(command[command.index('--clothforge-params') + 1])
    assert params['friction'] == .8 and params['cloth_iterations'] == 12
    assert '--workstation-usd' in command
