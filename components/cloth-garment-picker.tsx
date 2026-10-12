'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { assetHref, type AssetRecord } from '@/lib/asset-types';
import { pbrDefaults, type Appearance, type PbrMaterial } from '@/lib/pbr-material-types';
import { AppearanceControls, type AppearanceOptions } from './garment-appearance-panel';
import { ClothGarmentPreview } from './cloth-garment-preview';
import { Button } from './ui/button';

export function previewAppearance(record: AssetRecord, material?: PbrMaterial): Appearance {
  const saved = record.data.appearance as Appearance | undefined;
  return saved ?? { texture: 'none', color: '#ffffff', roughness: .9, ...pbrDefaults,
    material_id: material?.asset_id ?? null, material_version: material?.version ?? null };
}

export function ClothGarmentPicker({ variants, materials, selected, onSelectionChange }: {
  variants: AssetRecord[]; materials: PbrMaterial[]; selected: string[]; onSelectionChange: (ids: string[]) => void;
}) {
  const [record, setRecord] = useState(variants[0]);
  const [value, setValue] = useState<Appearance>(() => previewAppearance(variants[0], materials[0]));
  const [options, setOptions] = useState<AppearanceOptions>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const material = materials.find(m => m.asset_id === value.material_id && m.version === value.material_version);
  const sizes = [...variants].sort((a,b) => Number((a.data.parameters as Record<string, number>).length_m) - Number((b.data.parameters as Record<string, number>).length_m));
  const dimensions = record.data.parameters as Record<string, number>;
  useEffect(() => {
    const controller = new AbortController(); setOptions(undefined); setError('');
    void api<AppearanceOptions>(`/assets/${encodeURIComponent(record.asset_id)}/appearance-options?version=${record.version}`, { signal: controller.signal })
      .then(next => { if (!controller.signal.aborted) setOptions({ ...next, materials }); })
      .catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, [record.asset_id, record.version, materials]);
  async function saveAndOpen() {
    if (!options) return;
    setBusy(true); setError('');
    const { asset_id, kind, name, description, tags, engines, data, references, artifacts } = record;
    const texture = options.textures.find(t => t.id === value.texture);
    try {
      const result = await api<{ record: AssetRecord }>('/assets', { method: 'POST', body: JSON.stringify({ expected_version: record.version,
        draft: { asset_id, kind, name, description, tags, engines, references,
          data: { ...data, appearance: { ...value, texture_sha256: texture?.artifact?.sha256 ?? null } },
          artifacts: [...artifacts.filter(a => a.role !== 'visual_texture'), ...(texture?.artifact ? [texture.artifact] : [])],
          change_note: '衣物库实时预览：保存选定尺寸变体的材质外观',
        } }) });
      window.location.href = `/sessions/new?engine=isaac_sim&scene=bimanual_tabletop_v17_clothforge&garment=${encodeURIComponent(result.record.asset_id)}&version=${result.record.version}`;
    } catch (e) { setError(String(e)); setBusy(false); }
  }
  return <div className="mt-3 space-y-3" data-garment-picker={record.asset_id}>
    <label className="block text-xs">衣长／尺寸变体<select aria-label="衣长尺寸" className="mt-1 w-full rounded border bg-background p-2" disabled={busy} value={record.asset_id} onChange={e => setRecord(variants.find(v => v.asset_id === e.target.value)!)}>{sizes.map(v => {
      const p = v.data.parameters as Record<string, number>;
      return <option key={v.asset_id} value={v.asset_id}>{v.name} · 长 {(p.length_m * 100).toFixed(1)} / {p.waist_width_m ? '腰宽' : '宽'} {((p.width_m ?? p.waist_width_m) * 100).toFixed(1)} cm</option>;
    })}</select></label>
    <p className="text-xs text-muted-foreground">长 {(dimensions.length_m * 100).toFixed(1)} · {dimensions.waist_width_m ? '腰宽' : '宽'} {((dimensions.width_m ?? dimensions.waist_width_m) * 100).toFixed(1)} cm{dimensions.sleeve_m ? ` · 袖长参数 ${(dimensions.sleeve_m * 100).toFixed(1)} cm` : ''}</p>
    <ClothGarmentPreview record={record} appearance={value} material={material} />
    {options && <AppearanceControls value={value} options={options} onChange={setValue} disabled={busy} showPreview={false} />}
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <Button size="sm" disabled={busy || !options} onClick={() => void saveAndOpen()}>{busy ? '保存中…' : '保存外观并进入工位'}</Button>
      <a className="text-primary" href={assetHref(record.asset_id, record.version)}>物理调参／详情</a>
      <label className="flex items-center gap-2"><input type="checkbox" checked={selected.includes(record.asset_id)} onChange={e => onSelectionChange(e.target.checked ? [...selected, record.asset_id] : selected.filter(id => id !== record.asset_id))} />加入批量</label>
    </div>
    <p className="text-xs text-muted-foreground">尺寸切换使用对应真实网格；外观在保存后用于工位及录制。</p>
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </div>;
}
