import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from robot_data_contracts.pbr_material import Appearance
from robot_data_studio.services.asset_service import AssetRegistry
from robot_data_studio.services import pbr_material_service as service
from robot_data_studio.routes.pbr_materials import router


def png(value=128):
    def chunk(name, content):
        return struct.pack('>I', len(content)) + name + content + struct.pack('>I', zlib.crc32(name + content))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\0' + bytes([value]*6))*2)) + chunk(b'IEND', b'')


@pytest.fixture
def registry(tmp_path, monkeypatch):
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps({'schema_version': 1, 'sources': {'cc0-fabrics-v1': {'root': str(tmp_path / 'images')},
                                                                  'cc0-surfaces-v1': {'root': str(tmp_path / 'surfaces')}}}))
    registry = AssetRegistry(tmp_path / 'registry', sources)
    monkeypatch.setattr(service, 'AssetRegistry', lambda: registry)
    monkeypatch.setattr('robot_data_studio.routes.pbr_materials.AssetRegistry', lambda: registry)
    return registry


def test_upload_catalog_maps_and_pinned_hashes(registry):
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        response = client.post('/pbr-materials', data={'name': 'local fabric', 'license_name': 'CC0-1.0'},
            files={role: (role + '.png', png(), 'image/png') for role in service.ROLES})
        assert response.status_code == 201, response.text
        material = response.json()
        assert len(client.get('/pbr-materials').json()['items']) == 1
        for role in service.ROLES:
            assert client.get(material['maps'][role]['url']).content == png()
        resolved = service.resolve({'material_id': material['asset_id'], 'material_version': 1})
        assert set(resolved['maps']) == set(service.ROLES)
        from robot_data_contracts.pbr_material import verify_maps
        verify_maps(resolved)
        Path(resolved['maps']['normal']['path']).write_bytes(png(50))
        with pytest.raises(ValueError, match='changed'):
            verify_maps(resolved)
        with pytest.raises(ValueError, match='hash mismatch'):
            service.resolve({'material_id': material['asset_id'], 'material_version': 1})


def test_import_requires_three_valid_maps_and_does_not_assert_user_cc0(registry):
    with pytest.raises(ValueError):
        service.import_material('bad', {'base_color': png()})
    with pytest.raises(ValueError):
        service.import_material('bad', {role: b'bad' for role in service.ROLES})
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        response = client.post('/pbr-materials', data={'name': 'my texture'},
            files={role: (role + '.png', png(), 'image/png') for role in service.ROLES})
        assert response.status_code == 201
        assert response.json()['data']['license'] == 'user-provided'
    with pytest.raises(ValueError):
        Appearance(material_id='MAT-unpinned')


def test_pbr_generation_snapshot_preserves_maps_and_detects_changes(registry):
    import sys
    sys.path.insert(0, '/data/zhanghejun/robot-data-generation/src')
    from robot_data_generation.cloth_appearance import build_plan, validate_plan
    material = service.import_material('fabric', {role: png() for role in service.ROLES})
    appearance = service.resolve({'material_id': material['asset_id'], 'material_version': 1,
                                  'color_mode': 'tint', 'normal_strength': .5, 'uv_scale': 4})
    plan = build_plan('test', [{'hashes': {}}], [appearance], Path('/unused'))
    attempt = plan['attempts'][0]['appearance']
    assert attempt['maps'] == appearance['maps'] and attempt['material_version'] == 1
    validate_plan(plan, check_sources=True)
    Path(attempt['maps']['roughness']['path']).write_bytes(png(10))
    with pytest.raises(ValueError, match='changed'):
        validate_plan(plan, check_sources=True)


def test_garment_saved_material_and_override_clear(registry):
    from robot_data_contracts.asset import AssetDraft
    from robot_data_studio.services.garment_appearance import resolve_appearance
    material = service.import_material('fabric', {role: png() for role in service.ROLES})
    garment = AssetDraft(asset_id='MDL-garment', kind='model', name='garment', tags=['clothforge'],
        data={'appearance': {'material_id': material['asset_id'], 'material_version': 1,
                            'normal_strength': .5, 'uv_scale': 4}}, change_note='test')
    resolved = resolve_appearance(registry, garment)
    assert len(resolved['maps']) == 3 and resolved['normal_strength'] == .5
    assert resolved['uv_scale'] == 4 and resolved['material_version'] == 1
    legacy = resolve_appearance(registry, garment, {'visual_material_id': None, 'visual_material_version': None})
    assert legacy['texture'] == 'none' and 'maps' not in legacy


def test_environment_upload_preserves_category_and_local_license(registry):
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        response = client.post('/pbr-materials', data={'name': 'wood', 'category': 'tabletop'},
            files={role: (role+'.png', png(), 'image/png') for role in service.ROLES})
        assert response.status_code == 201, response.text
        result = response.json()
        assert result['data']['category'] == 'tabletop'
        assert result['data']['license'] == 'user-provided'
        assert all(item['artifact']['source_id'] == 'cc0-surfaces-v1' for item in result['maps'].values())
        response = client.post('/pbr-materials', data={'name': 'bad', 'category': 'unknown'},
            files={role: (role+'.png', png(), 'image/png') for role in service.ROLES})
        assert response.status_code == 422
