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
  minimum: number | null;
  maximum: number | null;
  default: number | string;
  step: number | null;
  scale: 'linear' | 'log';
  choices: string[];
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
  renderer_profiles: Array<{ id: string; label: string; description: string; profile_version: number; rendering_mode: 'performance' | 'balanced' | 'quality' }>;
  physics_backends: Array<{ id: string; label: string; description: string }>;
  session_limits?: {
    target_episodes?: {
      minimum: number;
      maximum: number;
      default: number;
    };
  };
  runtime?: {
    headless: boolean;
    uses_gpu: boolean;
    uses_collector_port: boolean;
  };
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
  const [rendererProfile, setRendererProfile] = useState('');
  const [physicsBackend, setPhysicsBackend] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [sceneParams, setSceneParams] = useState<Record<string, number | string>>({});
  const [busy, setBusy] = useState(false);
  // `key` is set when the backend named a scene parameter as the reason, so the
  // message can sit against that field instead of only in the page banner.
  const [error, setError] = useState<{ message: string; key?: string }>();

  const selectedEngine = useMemo(
    () => engines.find((item) => item.id === engine),
    [engine, engines],
  );
  const scenes = useMemo(
    () => Object.entries(selectedEngine?.scenes ?? {}).map(([id, value]) => ({ id, ...value })),
    [selectedEngine],
  );
  const selected = useMemo(() => scenes.find((item) => item.id === scene), [scene, scenes]);
  // Categorical parameters (which garment the task wears) are part of choosing
  // the task, so they sit beside the scene picker rather than in the advanced
  // numeric block.
  const choiceParameters = useMemo(
    () => (selected?.parameters ?? []).filter((parameter) => parameter.choices.length > 0),
    [selected],
  );
  const numericParameters = useMemo(
    () => (selected?.parameters ?? []).filter((parameter) => parameter.choices.length === 0),
    [selected],
  );
  const episodeLimits = selectedEngine?.session_limits?.target_episodes ?? {
    minimum: 1,
    maximum: 10000,
    default: selectedEngine?.capabilities.batch_generation ? 1 : 50,
  };
  const usesCollectorPort = selectedEngine?.runtime?.uses_collector_port ?? true;
  const targetValid = target >= episodeLimits.minimum && target <= episodeLimits.maximum;

  function selectDescriptor(descriptor: Engine) {
    setEngine(descriptor.id);
    setScene(Object.keys(descriptor.scenes)[0] ?? '');
    setMode(descriptor.control_modes.includes('gello') ? 'gello' : descriptor.control_modes[0]);
    setCameraProfile(descriptor.camera_profiles[0]?.id ?? '');
    setRendererProfile(descriptor.renderer_profiles.find((profile) => profile.rendering_mode === 'balanced')?.id ?? descriptor.renderer_profiles[0]?.id ?? '');
    setPhysicsBackend(descriptor.physics_backends.find((backend) => backend.id === 'physx')?.id ?? descriptor.physics_backends[0]?.id ?? '');
    setTarget(
      descriptor.session_limits?.target_episodes?.default ??
        (descriptor.capabilities.batch_generation ? 1 : 50),
    );
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
      .catch((caught) => setError({ message: caught instanceof Error ? caught.message : '加载引擎失败' }));
  }, []);

  useEffect(() => {
    setSceneParams(Object.fromEntries(
      (selected?.parameters ?? []).map((parameter) => [parameter.key, parameter.default]),
    ));
    setAdvanced(false);
    setError(undefined);
  }, [selected]);

  function updateSceneParam(key: string, value: number | string) {
    setSceneParams((current) => ({ ...current, [key]: value }));
    // A rejection no longer applies once the value it named is edited.
    setError((current) => (current?.key === key ? undefined : current));
  }

  async function submit() {
    if (!selectedEngine || !selected) return;
    if (!targetValid) {
      setError({
        message: `目标 Episode 数必须在 ${episodeLimits.minimum}～${episodeLimits.maximum} 之间`,
      });
      return;
    }
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
          ...(usesCollectorPort ? { port } : {}),
          gpu,
          control_fps: fps,
          sim_dt: 0.01,
          physics_steps_per_control: Math.round(1 / (fps * 0.01)),
          width: 640,
          height: 480,
          camera_profile_id: cameraProfile,
          ...(rendererProfile ? { renderer_profile_id: rendererProfile } : {}),
          ...(physicsBackend ? { physics_backend: physicsBackend } : {}),
          scene_params: sceneParams,
        }),
      });
      window.location.href = `/sessions/${session.id}`;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '创建会话失败';
      // The scene plugin reports a rejected parameter as `key=value ...`, so the
      // reason can be pinned to the field that caused it.
      const named = message.match(/^([a-z][a-z0-9_]*)=/)?.[1];
      const key = selected.parameters.some((parameter) => parameter.key === named) ? named : undefined;
      setError({ message, key });
      // Numeric parameters sit in the collapsed block; open it, or the field the
      // message points at is off screen.
      if (key) setAdvanced(true);
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
        {error && !error.key && (
          <Alert variant="destructive">
            <AlertTitle>会话配置不可用</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
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
                <Field label="目标 Episode 数">
                  <Input
                    type="number"
                    min={episodeLimits.minimum}
                    max={episodeLimits.maximum}
                    value={target}
                    onChange={(event) => setTarget(Number(event.target.value))}
                  />
                  <p className={`text-xs ${targetValid ? 'text-muted-foreground' : 'text-destructive'}`}>
                    当前引擎允许 {episodeLimits.minimum}～{episodeLimits.maximum} 个 Episode
                  </p>
                </Field>
                <div className="sm:col-span-2">
                  <Label className="mb-2">场景插件</Label>
                  <NativeSelect className="w-full" value={scene} onChange={(event) => setScene(event.target.value)}>
                    {scenes.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.label} · {item.family}</NativeSelectOption>)}
                  </NativeSelect>
                  {selected?.description && <p className="mt-2 text-xs text-muted-foreground">{selected.description}</p>}
                </div>
                {choiceParameters.map((parameter) => (
                  <div className="sm:col-span-2" key={parameter.key}>
                    <Label className="mb-2">{parameter.label}</Label>
                    <NativeSelect
                      className="w-full"
                      aria-invalid={error?.key === parameter.key || undefined}
                      value={String(sceneParams[parameter.key] ?? parameter.default)}
                      onChange={(event) => updateSceneParam(parameter.key, event.target.value)}
                    >
                      {parameter.choices.map((choice) => <NativeSelectOption key={choice} value={choice}>{choice}</NativeSelectOption>)}
                    </NativeSelect>
                    {error?.key === parameter.key
                      ? <p className="mt-2 text-xs text-destructive">{error.message}</p>
                      : <p className="mt-2 text-xs text-muted-foreground">该任务使用的物件，由场景插件提供可选值。</p>}
                  </div>
                ))}
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
                {Boolean(selectedEngine?.renderer_profiles.length) && <div>
                  <Label className="mb-2">Renderer Profile</Label>
                  <NativeSelect className="w-full" value={rendererProfile} onChange={(event) => setRendererProfile(event.target.value)}>
                    {selectedEngine?.renderer_profiles.map((profile) => <NativeSelectOption key={profile.id} value={profile.id}>{profile.label} · {profile.rendering_mode} · v{profile.profile_version}</NativeSelectOption>)}
                  </NativeSelect>
                  <p className="mt-2 text-xs text-muted-foreground">{selectedEngine?.renderer_profiles.find((profile) => profile.id === rendererProfile)?.description}</p>
                </div>}
                {Boolean(selectedEngine?.physics_backends.length) && <div>
                  <Label className="mb-2">Physics Backend</Label>
                  <NativeSelect className="w-full" value={physicsBackend} onChange={(event) => setPhysicsBackend(event.target.value)}>
                    {selectedEngine?.physics_backends.map((backend) => <NativeSelectOption key={backend.id} value={backend.id}>{backend.label}</NativeSelectOption>)}
                  </NativeSelect>
                  <p className="mt-2 text-xs text-muted-foreground">{selectedEngine?.physics_backends.find((backend) => backend.id === physicsBackend)?.description}</p>
                </div>}
              </CardContent>
            </Card>

            <Card className="instrument-card">
              <CardHeader><CardTitle>4. 运行参数</CardTitle><CardDescription>参数控件完全由当前 ScenePlugin 描述生成。</CardDescription></CardHeader>
              <CardContent className="space-y-4">
                <div className={`grid gap-4 ${usesCollectorPort ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
                  <Field label={selectedEngine?.runtime?.headless ? 'Worker GPU' : 'GPU'}><Input type="number" min={0} value={gpu} onChange={(event) => setGpu(Number(event.target.value))} /></Field>
                  {usesCollectorPort && <Field label="Collector 端口"><Input type="number" min={1024} value={port} onChange={(event) => setPort(Number(event.target.value))} /></Field>}
                  <Field label="控制频率 (Hz)"><Input type="number" min={1} max={120} value={fps} onChange={(event) => setFps(Number(event.target.value))} /></Field>
                </div>
                {Boolean(numericParameters.length) && (
                  <>
                    <Button type="button" variant="outline" onClick={() => setAdvanced(!advanced)}>
                      <SlidersHorizontal />场景参数<ChevronDown className={advanced ? 'rotate-180 transition-transform' : 'transition-transform'} />
                    </Button>
                    {advanced && (
                      <div className="grid gap-4 rounded-lg border border-border/70 bg-background/40 p-4 sm:grid-cols-2">
                        {numericParameters.map((parameter) => (
                          <Field key={parameter.key} label={`${parameter.label}${parameter.unit ? ` (${parameter.unit})` : ''}`}>
                            <Input
                              type="number"
                              min={parameter.minimum ?? undefined}
                              max={parameter.maximum ?? undefined}
                              step={parameter.step ?? 'any'}
                              aria-invalid={error?.key === parameter.key || undefined}
                              value={sceneParams[parameter.key] ?? parameter.default}
                              onChange={(event) => updateSceneParam(parameter.key, Number(event.target.value))}
                            />
                            {error?.key === parameter.key
                              ? <p className="text-xs text-destructive">{error.message}</p>
                              : parameter.scale === 'log' && parameter.minimum !== null && parameter.maximum !== null
                                ? <p className="text-xs text-muted-foreground">允许 {parameter.minimum} ～ {parameter.maximum}</p>
                                : null}
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
                <Summary label="Renderer" value={selectedEngine?.renderer_profiles.find((item) => item.id === rendererProfile)?.label ?? '引擎默认'} />
                <Summary label="Physics" value={selectedEngine?.physics_backends.find((item) => item.id === physicsBackend)?.label ?? '引擎默认'} />
                <Summary label="Quota" value={`${target} episodes`} />
                <Summary label="Worker" value={usesCollectorPort ? `GPU ${gpu} · :${port}` : `GPU ${gpu} · headless batch`} />
                <div className="rounded-lg border border-primary/25 bg-primary/5 p-3 text-xs leading-5 text-muted-foreground"><Check className="mr-1 inline size-3.5 text-primary" />状态、动作、图像、时间戳和引擎 provenance 会进入统一 Episode 索引。</div>
                <Button className="w-full" size="lg" disabled={busy || !dataset.trim() || !selectedEngine || !selected || !targetValid} onClick={submit}>{busy ? '创建中…' : '创建会话'}<ArrowRight /></Button>
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
