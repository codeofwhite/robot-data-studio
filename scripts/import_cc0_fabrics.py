"""Fetch the explicitly selected ambientCG PNG packages and register their maps."""
import json
from pathlib import Path
import urllib.request
import zipfile

from robot_data_studio.services.asset_service import AssetRegistry, AssetNotFound
from robot_data_studio.services.pbr_material_service import import_material, describe

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / 'config/cc0_fabrics.json').read_text())
    registry = AssetRegistry()
    root = Path(registry.sources()['cc0-fabrics-v1']['root'])
    archive_dir = root / 'downloads'
    archive_dir.mkdir(parents=True, exist_ok=True)
    for item in config['materials']:
        asset_id = 'MAT-ambientcg-' + item['id'].lower()
        try:
            record = registry.get(asset_id)
        except AssetNotFound:
            record = None
        if record:
            describe(record, registry)
            print('EXISTS', asset_id, flush=True)
            continue
        archive = archive_dir / (item['id'] + '_1K-PNG.zip')
        if not archive.exists():
            temporary = archive.with_suffix('.part')
            # The public CDN rejects urllib's default Python UA (HTTP 403/1010).
            request = urllib.request.Request(item['download_url'], headers={
                'User-Agent': 'Mozilla/5.0 RobotDataStudioMaterials/1.0', 'Referer': item['source_url']})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as output:
                while chunk := response.read(1024*1024):
                    output.write(chunk)
            temporary.replace(archive)
        with zipfile.ZipFile(archive) as package:
            images = {}
            for role, suffix in [('base_color', '_Color.png'), ('normal', '_NormalGL.png'), ('roughness', '_Roughness.png')]:
                names = [name for name in package.namelist() if name.endswith(suffix)]
                if len(names) != 1:
                    raise ValueError(f'{item["id"]}: expected exactly one {suffix}: {names}')
                images[role] = package.read(names[0])
        imported = import_material(item['name'], images, origin=item['source_url'],
                                   license_name='CC0-1.0', asset_id=asset_id, registry=registry)
        print('IMPORTED', imported['asset_id'], imported['version'], flush=True)
    (root / 'provenance.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
