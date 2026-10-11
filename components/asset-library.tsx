'use client';

import { useEffect, useState } from 'react';
import { Boxes, Plus, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PbrMaterialLibrary } from '@/components/pbr-material-library';
import { ValidationOverview } from '@/components/validation-overview';
import { AssetEditor } from '@/components/asset-detail';
import { api, API_BASE } from '@/lib/api';
import { assetHref, kindLabels, outcomeLabel, type AssetKind, type AssetList } from '@/lib/asset-types';

export function AssetLibrary() {
  const [view, setView] = useState<'overview' | 'index' | 'cloth' | 'pbr'>('overview');
  const [q, setQ] = useState('');
  const [kind, setKind] = useState('');
  const [engine, setEngine] = useState('');
  const [outcome, setOutcome] = useState('');
  const [integrity, setIntegrity] = useState('');
  const [offset, setOffset] = useState(0);
  const [showScanRecords, setShowScanRecords] = useState(false);
  const [tick, setTick] = useState(0);
  const [data, setData] = useState<AssetList>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const limit = 30;
  useEffect(() => { const requested = new URLSearchParams(window.location.search).get('view'); if (requested === 'cloth' || requested === 'pbr') setView(requested); }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      // config/validation 是 ClothForge 扫描的日志，属于「验证概览」；默认不混进资产索引
      const kindQuery = kind || (showScanRecords ? '' : 'model,scene,material');
      const query = new URLSearchParams({ q, kind: kindQuery, engine, outcome, integrity, offset: String(offset), limit: String(limit) });
      void api<AssetList>('/assets?' + query, { signal: controller.signal }).then(result => {
        if (!controller.signal.aborted) { setData(result); setError(''); }
      }).catch(caught => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : '加载失败');
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [q, kind, engine, outcome, integrity, offset, tick, showScanRecords]);

  return <div className="space-y-5">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><Badge variant="outline" className="mb-3">ASSET REGISTRY</Badge><h1 className="text-2xl font-semibold">资产与材料</h1><p className="mt-2 text-sm text-muted-foreground">按固定编号查找资产，追溯每个版本的配置、模型与验证证据。</p></div>
      <div className="flex gap-2"><Button variant="outline" onClick={() => setTick(tick + 1)}><RefreshCw className={loading ? 'animate-spin' : ''} />刷新</Button><Button onClick={() => setCreating(!creating)}><Plus />登记资产</Button></div>
    </div>
    {creating && <AssetEditor onCancel={() => setCreating(false)} />}
    <div className="flex flex-wrap gap-2" aria-label="资产页面视图"><Button variant={view === 'pbr' ? 'default' : 'outline'} onClick={() => setView('pbr')}>PBR 材质</Button><Button variant={view === 'cloth' ? 'default' : 'outline'} aria-pressed={view === 'cloth'} onClick={() => setView('cloth')}>衣物仿真</Button><Button variant={view === 'overview' ? 'default' : 'outline'} aria-pressed={view === 'overview'} onClick={() => setView('overview')}>验证概览</Button><Button variant={view === 'index' ? 'default' : 'outline'} aria-pressed={view === 'index'} onClick={() => setView('index')}>资产索引</Button></div>
    {view === 'pbr' ? <PbrMaterialLibrary /> : view === 'cloth' ? <ClothGallery refresh={tick} /> : view === 'overview' ? <ValidationOverview refresh={tick} /> : <>
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      {(Object.keys(kindLabels) as AssetKind[]).map(key => <button key={key} className={'rounded-xl border p-4 text-left transition-colors ' + (kind === key ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted/50')} onClick={() => { setKind(kind === key ? '' : key); setOffset(0); }}><span className="block text-sm text-muted-foreground">{kindLabels[key]}</span><strong className="mt-2 block font-mono text-2xl">{data?.counts[key] ?? '—'}</strong></button>)}
    </div>
    {error && <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</div>}
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Boxes className="size-4" />资产索引</CardTitle>
        <div className="grid gap-2 pt-3 md:grid-cols-2 xl:grid-cols-5">
          <label className="relative"><Search className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input aria-label="搜索资产名称或编号" className="pl-9" placeholder="名称、编号、标签…" value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} /></label>
          <NativeSelect aria-label="资产类型" value={kind} onChange={e => { setKind(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部类型</NativeSelectOption>{Object.entries(kindLabels).map(([key, label]) => <NativeSelectOption key={key} value={key}>{label}</NativeSelectOption>)}</NativeSelect>
          <NativeSelect aria-label="仿真引擎" value={engine} onChange={e => { setEngine(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部引擎</NativeSelectOption>{['genesis', 'isaac_sim', 'newton_vbd', 'newton', 'roboverse'].map(key => <NativeSelectOption key={key} value={key}>{key}</NativeSelectOption>)}</NativeSelect>
          <NativeSelect aria-label="验证结果" value={outcome} onChange={e => { setOutcome(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部记录结果</NativeSelectOption><NativeSelectOption value="passed">通过</NativeSelectOption><NativeSelectOption value="failed">失败</NativeSelectOption><NativeSelectOption value="unavailable">未判定</NativeSelectOption></NativeSelect>
          <NativeSelect aria-label="证据完整性" value={integrity} onChange={e => { setIntegrity(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部证据状态</NativeSelectOption><NativeSelectOption value="current">引用文件一致</NativeSelectOption><NativeSelectOption value="stale">证据过期 / 缺失</NativeSelectOption></NativeSelect>
        </div>
      </CardHeader>
      <CardContent><div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">{loading ? '正在核对版本与文件…' : '匹配 ' + (data?.total ?? 0) + ' 项'} · 默认显示各资产最新版本，历史版本在详情中查看。文件一致不等于物理验证通过。</p>
          <Button size="sm" variant={showScanRecords ? 'default' : 'outline'} aria-pressed={showScanRecords} onClick={() => { setShowScanRecords(!showScanRecords); setOffset(0); }}>{showScanRecords ? '隐藏扫描记录' : '显示扫描记录'}</Button>
        </div>
        <Table><TableHeader><TableRow><TableHead>资产 / 固定编号</TableHead><TableHead>类型</TableHead><TableHead>版本</TableHead><TableHead>引擎</TableHead><TableHead>记录结果</TableHead><TableHead>证据</TableHead></TableRow></TableHeader><TableBody>
          {!loading && !data?.items.length && <TableRow><TableCell colSpan={6} className="py-12 text-center text-muted-foreground">没有匹配资产，可调整筛选或登记新资产。</TableCell></TableRow>}
          {data?.items.map(record => <TableRow key={record.asset_id}><TableCell><a className="font-medium text-primary hover:underline" href={assetHref(record.asset_id)}>{record.name}</a><p className="mt-1 break-all font-mono text-xs text-muted-foreground">{record.asset_id}</p></TableCell><TableCell>{kindLabels[record.kind]}</TableCell><TableCell className="font-mono">v{record.version}</TableCell><TableCell className="text-xs">{record.engines.join(' · ') || '通用'}</TableCell><TableCell><Badge variant={record.data.outcome === 'failed' ? 'destructive' : 'outline'}>{outcomeLabel(record.data.outcome)}</Badge></TableCell><TableCell><Badge variant={record.integrity.status === 'stale' ? 'destructive' : 'outline'}>{record.integrity.status === 'current' ? '文件一致' : '证据过期'}</Badge></TableCell></TableRow>)}
        </TableBody></Table>
        <div className="mt-4 flex items-center justify-between"><span className="text-xs text-muted-foreground">{data?.revision_count ?? 0} 个已保存版本</span><div className="flex items-center gap-3"><Button variant="outline" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - limit))}>上一页</Button><span className="text-xs">{Math.floor(offset / limit) + 1}</span><Button variant="outline" disabled={loading || offset + limit >= (data?.total ?? 0)} onClick={() => setOffset(offset + limit)}>下一页</Button></div></div>
      </CardContent>
    </Card>
    </>}
  </div>;
}


function ClothGallery({ refresh }: { refresh: number }) {
  const [data, setData] = useState<AssetList>();
  const [error, setError] = useState('');
  const [category, setCategory] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void api<AssetList>('/assets?q=clothforge&kind=model&engine=newton_vbd&limit=100', { signal: controller.signal }).then(setData).catch(caught => { if (!controller.signal.aborted) setError(String(caught)); });
    return () => controller.abort();
  }, [refresh]);
  const items = (data?.items ?? []).filter(item => !category || item.data.category === category);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold">选择一件衣物开始试验</h2><p className="mt-1 text-sm text-muted-foreground">查看三维形状，选择材料，调整参数，运行悬挂或落地并回看实际轨迹。</p></div><NativeSelect aria-label="衣物类别" value={category} onChange={event => setCategory(event.target.value)}><NativeSelectOption value="">全部衣物</NativeSelectOption><NativeSelectOption value="tshirt">T 恤</NativeSelectOption><NativeSelectOption value="trousers">长裤</NativeSelectOption><NativeSelectOption value="open_coat">开襟外套</NativeSelectOption></NativeSelect></div>
    <div className="space-y-1 rounded-lg border bg-muted/20 p-3 text-sm"><p>当前目录包含 3 种基础版型，每种版型有 10 个尺寸变体。同类衣物共用结构，主要改变长度、宽度与袖部尺寸。</p><p className="text-xs text-muted-foreground">缩略图自动缩放，展示仿真前形状；请按下方实际尺寸比较大小。材料差异需要通过悬挂或落地回放观察。当前模型尚无口袋、帽子、内衬等款式细节。</p></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!data && !error && <p className="text-sm text-muted-foreground">正在加载衣物…</p>}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{items.map(record => {
      const preview = record.artifacts.findIndex(a => a.role === 'preview');
      const parameters = record.data.parameters && typeof record.data.parameters === 'object' ? record.data.parameters as Record<string, unknown> : {};
      const dimensions = (record.data.category === 'trousers' ? [['length_m', '裤长'], ['waist_width_m', '腰部平铺宽'], ['hip_width_m', '臀部平铺宽']] : [['length_m', '衣长'], ['width_m', '衣身平铺宽'], ['sleeve_m', '袖长参数']]).flatMap(([key, label]) => {
        const value = parameters[key];
        return typeof value === 'number' && Number.isFinite(value) ? [{ key, label, cm: (value * 100).toFixed(1) }] : [];
      });
      return <Card key={record.asset_id} className="overflow-hidden"><a href={assetHref(record.asset_id, record.version)} className="block">
        {preview >= 0 && record.integrity.status === 'current' && <img loading="lazy" className="h-52 w-full bg-slate-100 object-contain" alt={record.name} src={API_BASE + '/assets/' + encodeURIComponent(record.asset_id) + '/versions/' + record.version + '/artifacts/' + preview} />}
        <CardContent className="space-y-3 pt-4"><div className="flex items-center justify-between gap-2"><strong>{record.name}</strong><Badge variant="outline">Newton VBD</Badge></div><p className="text-xs text-muted-foreground">基础版型的尺寸变体 · 悬挂 / 落地 · 3 种合成材料预设</p><dl aria-label="实际几何尺寸" className="grid grid-cols-3 gap-2 rounded-md bg-muted/30 p-2">{dimensions.map(dimension => <div key={dimension.key} data-cloth-dimension={dimension.key}><dt className="text-[11px] text-muted-foreground">{dimension.label}</dt><dd className="mt-1 text-sm font-medium tabular-nums">{dimension.cm} cm</dd></div>)}</dl><span className="inline-flex rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground">调参并运行</span>{record.integrity.status !== 'current' && <p className="text-xs text-destructive">来源证据失效，需修复后运行</p>}</CardContent>
      </a></Card>;
    })}</div>
    {data && <p className="text-xs text-muted-foreground">显示 {items.length} / {data.total} 个尺寸变体。预览仅展示初始几何；每次运行单独检查物理质量。</p>}
  </div>;
}
