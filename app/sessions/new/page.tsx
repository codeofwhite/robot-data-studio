'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Bot, Boxes, Check, ChevronDown, Keyboard, SlidersHorizontal } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { api } from '@/lib/api';
import type { Session } from '@/lib/types';

type Engine = {
  id: 'genesis' | 'isaac_sim';
  label: string;
  control_modes: Array<'keyboard' | 'gello'>;
  capabilities: Record<string, boolean>;
  scenes: Record<string, { label: string; family: string; params: Array<{ key: string }> }>;
  camera_profiles: Array<{ id: string; label: string; match_level: string; roles: string[] }>;
};

const fallbackEngines: Engine[] = [
  { id: 'genesis', label: 'Genesis / ClothTwin', control_modes: ['keyboard', 'gello'], capabilities: { recording: true, automatic_outcome: true }, scenes: { cloth_corner_lift: { label: '布料角点抓取抬升', family: 'cloth', params: [] }, rigid_pick_place: { label: '刚体抓取放置', family: 'general', params: [] }, push_to_zone: { label: '推到目标区域', family: 'general', params: [] }, place_in_bin: { label: '抓取放入容器', family: 'general', params: [] } }, camera_profiles: [{ id: 'lab_d435i_dual_v1', label: '实验室双 Intel RealSense D435i', match_level: 'nominal_pending_intrinsics', roles: ['agentview', 'wrist'] }] },
  { id: 'isaac_sim', label: 'Isaac Sim / Isaac Lab', control_modes: ['gello'], capabilities: { recording: true, automatic_outcome: false, webrtc: true }, scenes: { franka_empty: { label: 'Franka 空场景遥操采集', family: 'general', params: [] } }, camera_profiles: [{ id: 'lab_d435i_dual_v1', label: '实验室双 Intel RealSense D435i', match_level: 'nominal_pending_intrinsics', roles: ['agentview', 'wrist'] }] },
];

const clothDefaults: Record<string, number> = {
  cloth_static_friction: 0.4,
  cloth_kinetic_friction: 0.3,
  cloth_stretch_compliance: 1e-7,
  cloth_bending_compliance: 1e-5,
  cloth_scale: 0.55,
  required_corner_lift_m: 0.15,
  required_hold_frames: 5,
};

export default function NewSessionPage() {
  const [engines, setEngines] = useState<Engine[]>(fallbackEngines);
  const [engine, setEngine] = useState<'genesis' | 'isaac_sim'>('genesis');
  const [dataset, setDataset] = useState('clothtwin_pilot');
  const [scene, setScene] = useState('cloth_corner_lift');
  const [mode, setMode] = useState<'keyboard' | 'gello'>('gello');
  const [target, setTarget] = useState(50);
  const [port, setPort] = useState(8080);
  const [gpu, setGpu] = useState(0);
  const [fps, setFps] = useState(10);
  const [cameraProfile, setCameraProfile] = useState('lab_d435i_dual_v1');
  const [advanced, setAdvanced] = useState(false);
  const [cloth, setCloth] = useState(clothDefaults);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const selectedEngine = useMemo(() => engines.find((item) => item.id === engine) ?? engines[0], [engine, engines]);
  const scenes = useMemo(() => Object.entries(selectedEngine?.scenes ?? {}).map(([id, value]) => ({ id, ...value })), [selectedEngine]);
  const selected = useMemo(() => scenes.find((item) => item.id === scene), [scene, scenes]);

  useEffect(() => {
    void api<Engine[]>('/engines').then(setEngines).catch(() => undefined);
  }, []);

  function chooseEngine(next: 'genesis' | 'isaac_sim') {
    const descriptor = engines.find((item) => item.id === next) ?? fallbackEngines.find((item) => item.id === next)!;
    setEngine(next);
    setScene(Object.keys(descriptor.scenes)[0]);
    setMode(descriptor.control_modes.includes('gello') ? 'gello' : descriptor.control_modes[0]);
    setCameraProfile(descriptor.camera_profiles[0]?.id ?? 'lab_d435i_dual_v1');
  }

  async function submit() {
    setBusy(true); setError(undefined);
    try {
      const session = await api<Session>('/sessions', {
        method: 'POST',
        body: JSON.stringify({
          engine_id: engine, dataset_name: dataset, scene_id: scene, control_mode: mode, target_episodes: target,
          port, gpu, control_fps: fps, physics_steps_per_control: 2, width: 640, height: 480,
          camera_profile_id: cameraProfile,
          scene_params: scene === 'cloth_corner_lift' ? cloth : {},
        }),
      });
      window.location.href = `/sessions/${session.id}`;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建会话失败'); setBusy(false);
    }
  }

  return (
    <AppShell current="sessions">
      <div className="mx-auto max-w-5xl space-y-6">
        <div><Badge variant="outline" className="mb-3">NEW SESSION</Badge><h1 className="text-2xl font-semibold tracking-tight md:text-3xl">新建采集会话</h1><p className="mt-2 text-sm text-muted-foreground">一次确定数据去向、任务、控制器与运行参数。创建后再显式启动 worker。</p></div>
        {error && <Alert variant="destructive"><AlertTitle>无法创建会话</AlertTitle><AlertDescription>{error}。请确认后端已在 8010 端口运行。</AlertDescription></Alert>}
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <div className="space-y-4">
            <Card className="instrument-card"><CardHeader><CardTitle>1. 仿真引擎</CardTitle><CardDescription>会话固定记录引擎、场景和控制来源，切换时启动独立 Worker。</CardDescription></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2"><ModeCard active={engine === 'genesis'} icon={Boxes} title="Genesis" note="ClothTwin 场景与自动任务判据" onClick={() => chooseEngine('genesis')} /><ModeCard active={engine === 'isaac_sim'} icon={Bot} title="Isaac Sim" note="Isaac Lab + WebRTC + 通用 Episode" onClick={() => chooseEngine('isaac_sim')} /></CardContent></Card>
            <Card className="instrument-card"><CardHeader><CardTitle>2. 数据与任务</CardTitle><CardDescription>原始 Episode 写入 Studio 数据目录，引擎仓库不保存采集结果。</CardDescription></CardHeader><CardContent className="grid gap-4 sm:grid-cols-2"><Field label="Dataset 名称"><Input value={dataset} onChange={(event) => setDataset(event.target.value)} /></Field><Field label="目标 Episode 数"><Input type="number" min={1} max={10000} value={target} onChange={(event) => setTarget(Number(event.target.value))} /></Field><div className="sm:col-span-2"><Label className="mb-2">场景插件</Label><NativeSelect className="w-full" value={scene} onChange={(event) => setScene(event.target.value)}>{scenes.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.label} · {item.family}</NativeSelectOption>)}</NativeSelect></div></CardContent></Card>
            <Card className="instrument-card"><CardHeader><CardTitle>3. 控制与相机</CardTitle><CardDescription>控制来源和 Sensor Profile 都会固化在 Session 与 Episode 中。</CardDescription></CardHeader><CardContent className="space-y-4"><div className="grid gap-3 sm:grid-cols-2">{selectedEngine?.control_modes.includes('gello') && <ModeCard active={mode === 'gello'} icon={Bot} title="GELLO" note="浏览器 Web Serial 直连" onClick={() => setMode('gello')} />}{selectedEngine?.control_modes.includes('keyboard') && <ModeCard active={mode === 'keyboard'} icon={Keyboard} title="Keyboard" note="浏览器键盘遥操作" onClick={() => setMode('keyboard')} />}</div><div><Label className="mb-2">Sensor Profile</Label><NativeSelect className="w-full" value={cameraProfile} onChange={(event) => setCameraProfile(event.target.value)}>{selectedEngine?.camera_profiles.map((profile) => <NativeSelectOption key={profile.id} value={profile.id}>{profile.label} · {profile.roles.join(' + ')} · {profile.match_level}</NativeSelectOption>)}</NativeSelect></div></CardContent></Card>
            <Card className="instrument-card"><CardHeader><CardTitle>4. 运行参数</CardTitle><CardDescription>GPU 由引擎适配器按各自的安全方式路由。</CardDescription></CardHeader><CardContent className="space-y-4"><div className="grid gap-4 sm:grid-cols-3"><Field label="GPU"><Input type="number" min={0} value={gpu} onChange={(event) => setGpu(Number(event.target.value))} /></Field><Field label="Collector 端口"><Input type="number" min={1024} value={port} onChange={(event) => setPort(Number(event.target.value))} /></Field><Field label="控制频率 (Hz)"><Input type="number" min={1} max={120} value={fps} onChange={(event) => setFps(Number(event.target.value))} /></Field></div>{engine === 'genesis' && scene === 'cloth_corner_lift' && <><Button type="button" variant="outline" onClick={() => setAdvanced(!advanced)}><SlidersHorizontal /> 布料参数 <ChevronDown className={advanced ? 'rotate-180 transition-transform' : 'transition-transform'} /></Button>{advanced && <div className="grid gap-4 rounded-lg border border-border/70 bg-background/40 p-4 sm:grid-cols-2">{Object.entries(cloth).map(([key, value]) => <Field key={key} label={parameterLabel(key)}><Input type="number" value={value} step={key.includes('compliance') ? 'any' : key.includes('frames') ? 1 : 0.01} onChange={(event) => setCloth({ ...cloth, [key]: Number(event.target.value) })} /></Field>)}</div>}</>}</CardContent></Card>
          </div>
          <aside className="space-y-4"><Card className="instrument-card sticky top-20"><CardHeader><CardTitle>会话摘要</CardTitle><CardDescription>创建不等于启动，可在下一页再次确认。</CardDescription></CardHeader><CardContent className="space-y-3 text-sm"><Summary label="Engine" value={selectedEngine?.label ?? engine} /><Summary label="Task" value={selected?.label ?? scene} /><Summary label="Control" value={mode.toUpperCase()} /><Summary label="Camera" value={selectedEngine?.camera_profiles.find((item) => item.id === cameraProfile)?.label ?? cameraProfile} /><Summary label="Quota" value={`${target} episodes`} /><Summary label="Worker" value={`GPU ${gpu} · :${port}`} /><div className="rounded-lg border border-primary/25 bg-primary/5 p-3 text-xs leading-5 text-muted-foreground"><Check className="mr-1 inline size-3.5 text-primary" /> 状态、动作、图像、时间戳和引擎 provenance 会进入统一 Episode 索引。</div><Button className="w-full" size="lg" disabled={busy || !dataset.trim()} onClick={submit}>{busy ? '创建中…' : '创建会话'} <ArrowRight /></Button></CardContent></Card></aside>
        </div>
      </div>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <div className="space-y-2"><Label>{label}</Label>{children}</div>; }
function ModeCard({ active, icon: Icon, title, note, onClick }: { active: boolean; icon: typeof Bot; title: string; note: string; onClick: () => void }) { return <button type="button" onClick={onClick} className={`rounded-xl border p-4 text-left transition-colors ${active ? 'border-primary bg-primary/8' : 'border-border/70 bg-background/35 hover:border-primary/40'}`}><div className="flex items-center justify-between"><Icon className={active ? 'size-5 text-primary' : 'size-5 text-muted-foreground'} />{active && <Check className="size-4 text-primary" />}</div><strong className="mt-4 block">{title}</strong><span className="mt-1 block text-xs leading-5 text-muted-foreground">{note}</span></button>; }
function Summary({ label, value }: { label: string; value: string }) { return <div className="flex items-start justify-between gap-4 border-b border-border/60 pb-2"><span className="text-muted-foreground">{label}</span><strong className="text-right font-mono text-xs">{value}</strong></div>; }
function parameterLabel(key: string) { return ({ cloth_static_friction: '静摩擦', cloth_kinetic_friction: '动摩擦', cloth_stretch_compliance: '拉伸柔顺度', cloth_bending_compliance: '弯曲柔顺度', cloth_scale: '布料尺寸', required_corner_lift_m: '成功抬升高度 (m)', required_hold_frames: '成功保持帧数' } as Record<string, string>)[key] ?? key; }
