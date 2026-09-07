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

type SceneParameter = {
  key: string;
  label: string;
  unit: string;
  minimum: number;
  maximum: number;
  default: number;
  step: number | null;
  scale: 'linear' | 'log';
};

type Engine = {
  id: string;
  label: string;
  control_modes: Array<'keyboard' | 'gello' | 'scripted'>;
  capabilities: Record<string, boolean>;
  scenes: Record<string, {
    label: string;
    description?: string;
    family: string;
    parameters: SceneParameter[];
  }>;
  camera_profiles: Array<{ id: string; label: string; match_level: string; roles: string[] }>;
};

export default function NewSessionPage() {
  const [engines, setEngines] = useState<Engine[]>([]);
  const [engine, setEngine] = useState('');
  const [dataset, setDataset] = useState('robot_data_pilot');
  const [scene, setScene] = useState('');
  const [mode, setMode] = useState<'keyboard' | 'gello' | 'scripted'>('gello');
  const [target, setTarget] = useState(50);
  const [port, setPort] = useState(8080);
  const [gpu, setGpu] = useState(0);
  const [fps, setFps] = useState(10);
  const [cameraProfile, setCameraProfile] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [sceneParams, setSceneParams] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const selectedEngine = useMemo(
    () => engines.find((item) => item.id === engine),
    [engine, engines],
  );
  const scenes = useMemo(
    () => Object.entries(selectedEngine?.scenes ?? {}).map(([id, value]) => ({ id, ...value })),
    [selectedEngine],
  );
  const selected = useMemo(() => scenes.find((item) => item.id === scene), [scene, scenes]);

  function selectDescriptor(descriptor: Engine) {
    setEngine(descriptor.id);
    setScene(Object.keys(descriptor.scenes)[0] ?? '');
    setMode(descriptor.control_modes.includes('gello') ? 'gello' : descriptor.control_modes[0]);
    setCameraProfile(descriptor.camera_profiles[0]?.id ?? '');
    setTarget(descriptor.capabilities.batch_generation ? 1 : 50);
    setFps(descriptor.capabilities.batch_generation ? 20 : 10);
    setAdvanced(false);
  }

  useEffect(() => {
    void api<Engine[]>('/engines')
      .then((descriptors) => {
        if (!descriptors.length) throw new Error('后端没有注册采集引擎');
        setEngines(descriptors);
        selectDescriptor(descriptors[0]);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : '加载引擎失败'));
  }, []);

  useEffect(() => {
    setSceneParams(Object.fromEntries(
      (selected?.parameters ?? []).map((parameter) => [parameter.key, parameter.default]),
    ));
    setAdvanced(false);
  }, [selected]);

  async function submit() {
    if (!selectedEngine || !selected) return;
    setBusy(true);
    setError(undefined);
    try {
      const session = await api<Session>('/sessions', {
        method: 'POST',
        body: JSON.stringify({
          engine_id: engine,
          dataset_name: dataset,
          scene_id: scene,
          control_mode: mode,
          target_episodes: target,
          port,
          gpu,
          control_fps: fps,
          sim_dt: 0.01,
          physics_steps_per_control: Math.round(1 / (fps * 0.01)),
          width: 640,
          height: 480,
          camera_profile_id: cameraProfile,
          scene_params: sceneParams,
        }),
      });
      window.location.href = `/sessions/${session.id}`;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建会话失败');
      setBusy(false);
    }
  }

  return (
    <AppShell current="sessions">
      <div className="mx-auto max-w-5xl space-y-6">
        <div>
          <Badge variant="outline" className="mb-3">NEW SESSION</Badge>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">新建采集会话</h1>
          <p className="mt-2 text-sm text-muted-foreground">一次确定数据去向、场景插件、控制器与运行参数。创建后再显式启动 worker。</p>
        </div>
        {error && (
          <Alert variant="destructive">
            <AlertTitle>会话配置不可用</AlertTitle>
            <AlertDescription>{error}。场景列表只从后端 ScenePlugin 描述加载。</AlertDescription>
          </Alert>
        )}
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <div className="space-y-4">
            <Card className="instrument-card">
              <CardHeader><CardTitle>1. 仿真引擎</CardTitle><CardDescription>Studio 只编排引擎 Worker，场景能力来自各自插件。</CardDescription></CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                {engines.map((descriptor) => (
                  <ModeCard
                    key={descriptor.id}
                    active={engine === descriptor.id}
                    icon={descriptor.id === 'genesis' ? Boxes : Bot}
                    title={descriptor.label}
                    note={`${Object.keys(descriptor.scenes).length} 个场景 · ${descriptor.control_modes.join(' / ')}`}
                    onClick={() => selectDescriptor(descriptor)}
                  />
                ))}
              </CardContent>
            </Card>

            <Card className="instrument-card">
              <CardHeader><CardTitle>2. 数据与任务</CardTitle><CardDescription>原始 Episode 写入 Studio 数据目录，引擎仓库不保存采集结果。</CardDescription></CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <Field label="Dataset 名称"><Input value={dataset} onChange={(event) => setDataset(event.target.value)} /></Field>
                <Field label="目标 Episode 数"><Input type="number" min={1} max={10000} value={target} onChange={(event) => setTarget(Number(event.target.value))} /></Field>
                <div className="sm:col-span-2">
                  <Label className="mb-2">场景插件</Label>
                  <NativeSelect className="w-full" value={scene} onChange={(event) => setScene(event.target.value)}>
                    {scenes.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.label} · {item.family}</NativeSelectOption>)}
                  </NativeSelect>
                  {selected?.description && <p className="mt-2 text-xs text-muted-foreground">{selected.description}</p>}
                </div>
              </CardContent>
            </Card>

            <Card className="instrument-card">
              <CardHeader><CardTitle>3. 控制与相机</CardTitle><CardDescription>Studio 只选择控制方式；GELLO 串口与标定在 Collector 页面完成。</CardDescription></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  {selectedEngine?.control_modes.includes('gello') && <ModeCard active={mode === 'gello'} icon={Bot} title="GELLO" note="在 Collector 中连接与标定" onClick={() => setMode('gello')} />}
                  {selectedEngine?.control_modes.includes('keyboard') && <ModeCard active={mode === 'keyboard'} icon={Keyboard} title="Keyboard" note="Collector 键盘遥操作" onClick={() => setMode('keyboard')} />}
                  {selectedEngine?.control_modes.includes('scripted') && <ModeCard active={mode === 'scripted'} icon={Bot} title="Scripted" note="隔离 Worker 确定性批量生成" onClick={() => setMode('scripted')} />}
                </div>
                <div>
                  <Label className="mb-2">Sensor Profile</Label>
                  <NativeSelect className="w-full" value={cameraProfile} onChange={(event) => setCameraProfile(event.target.value)}>
                    {selectedEngine?.camera_profiles.map((profile) => <NativeSelectOption key={profile.id} value={profile.id}>{profile.label} · {profile.roles.join(' + ')} · {profile.match_level}</NativeSelectOption>)}
                  </NativeSelect>
                </div>
              </CardContent>
            </Card>

            <Card className="instrument-card">
              <CardHeader><CardTitle>4. 运行参数</CardTitle><CardDescription>参数控件完全由当前 ScenePlugin 描述生成。</CardDescription></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="GPU"><Input type="number" min={0} value={gpu} onChange={(event) => setGpu(Number(event.target.value))} /></Field>
                  <Field label="Collector 端口"><Input type="number" min={1024} value={port} onChange={(event) => setPort(Number(event.target.value))} /></Field>
                  <Field label="控制频率 (Hz)"><Input type="number" min={1} max={120} value={fps} onChange={(event) => setFps(Number(event.target.value))} /></Field>
                </div>
                {Boolean(selected?.parameters.length) && (
                  <>
                    <Button type="button" variant="outline" onClick={() => setAdvanced(!advanced)}>
                      <SlidersHorizontal />场景参数<ChevronDown className={advanced ? 'rotate-180 transition-transform' : 'transition-transform'} />
                    </Button>
                    {advanced && (
                      <div className="grid gap-4 rounded-lg border border-border/70 bg-background/40 p-4 sm:grid-cols-2">
                        {selected?.parameters.map((parameter) => (
                          <Field key={parameter.key} label={`${parameter.label}${parameter.unit ? ` (${parameter.unit})` : ''}`}>
                            <Input
                              type="number"
                              min={parameter.minimum}
                              max={parameter.maximum}
                              step={parameter.step ?? 'any'}
                              value={sceneParams[parameter.key] ?? parameter.default}
                              onChange={(event) => setSceneParams({ ...sceneParams, [parameter.key]: Number(event.target.value) })}
                            />
                          </Field>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          <aside className="space-y-4">
            <Card className="instrument-card sticky top-20">
              <CardHeader><CardTitle>会话摘要</CardTitle><CardDescription>创建不等于启动，可在下一页再次确认。</CardDescription></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Summary label="Engine" value={selectedEngine?.label ?? '等待后端'} />
                <Summary label="Task" value={selected?.label ?? '等待场景'} />
                <Summary label="Control" value={mode.toUpperCase()} />
                <Summary label="Camera" value={selectedEngine?.camera_profiles.find((item) => item.id === cameraProfile)?.label ?? '—'} />
                <Summary label="Quota" value={`${target} episodes`} />
                <Summary label="Worker" value={`GPU ${gpu} · :${port}`} />
                <div className="rounded-lg border border-primary/25 bg-primary/5 p-3 text-xs leading-5 text-muted-foreground"><Check className="mr-1 inline size-3.5 text-primary" />状态、动作、图像、时间戳和引擎 provenance 会进入统一 Episode 索引。</div>
                <Button className="w-full" size="lg" disabled={busy || !dataset.trim() || !selectedEngine || !selected} onClick={submit}>{busy ? '创建中…' : '创建会话'}<ArrowRight /></Button>
              </CardContent>
            </Card>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="space-y-2"><Label>{label}</Label>{children}</div>;
}

function ModeCard({ active, icon: Icon, title, note, onClick }: { active: boolean; icon: typeof Bot; title: string; note: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className={`rounded-xl border p-4 text-left transition-colors ${active ? 'border-primary bg-primary/8' : 'border-border/70 bg-background/35 hover:border-primary/40'}`}><div className="flex items-center justify-between"><Icon className={active ? 'size-5 text-primary' : 'size-5 text-muted-foreground'} />{active && <Check className="size-4 text-primary" />}</div><strong className="mt-4 block">{title}</strong><span className="mt-1 block text-xs leading-5 text-muted-foreground">{note}</span></button>;
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div className="flex items-start justify-between gap-4 border-b border-border/60 pb-2"><span className="text-muted-foreground">{label}</span><strong className="text-right font-mono text-xs">{value}</strong></div>;
}
