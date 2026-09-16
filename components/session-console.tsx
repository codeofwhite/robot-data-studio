'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  ExternalLink,
  Play,
  RefreshCw,
  Square,
  TriangleAlert,
} from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Progress,
  ProgressLabel,
  ProgressValue,
} from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { engineLabel } from '@/lib/engines';
import type { Session, WorkerRuntime } from '@/lib/types';

export function SessionConsole({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<Session>();
  const [worker, setWorker] = useState<WorkerRuntime>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextSession, nextWorker] = await Promise.all([
        api<Session>(`/sessions/${sessionId}`),
        api<WorkerRuntime>(`/sessions/${sessionId}/workers/status`),
      ]);
      setSession(nextSession);
      setWorker(nextWorker);
      setError(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败');
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function action(name: 'start' | 'stop' | 'scan') {
    setBusy(true);
    try {
      await api(
        `/sessions/${sessionId}/${name === 'scan' ? 'scan' : `workers/${name}`}`,
        { method: 'POST' },
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '操作失败');
    } finally {
      setBusy(false);
    }
  }

  if (!session && !error) {
    return (
      <AppShell current="sessions">
        <div className="space-y-4">
          <Skeleton className="h-12 w-80" />
          <Skeleton className="h-96 w-full" />
        </div>
      </AppShell>
    );
  }

  const count = session?.episode_count ?? 0;
  const target = session?.target_episodes ?? 1;
  const running = worker?.status === 'running' || worker?.status === 'starting';
  const active = running || worker?.status === 'stopping';
  const unhealthy = worker?.status === 'failed' || worker?.status === 'orphaned';
  const batchWorker = session?.engine_id === 'roboverse';

  return (
    <AppShell current="sessions">
      <div className="space-y-5">
        {error && (
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>会话异常</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {unhealthy && (
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>Worker {worker.status.toUpperCase()}</AlertTitle>
            <AlertDescription>{worker.error ?? '运行时状态异常，请查看 worker 日志。'}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Badge>{(worker?.status ?? session?.status ?? 'unknown').toUpperCase()}</Badge>
              <span className="font-mono text-xs text-muted-foreground">
                {sessionId}
              </span>
            </div>
            <h1 className="mt-3 text-2xl font-semibold">{session?.scene_id}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {session?.dataset_name} · {engineLabel(session?.engine_id)} · {session?.control_mode.toUpperCase()} · child
              PID {worker?.child_pid ?? '—'}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {active ? (
              <Button
                variant="destructive"
                disabled={busy || worker?.status === 'stopping'}
                onClick={() => action('stop')}
              >
                <Square />停止 Worker
              </Button>
            ) : (
              <Button disabled={busy} onClick={() => action('start')}>
                <Play />启动 Worker
              </Button>
            )}
            <Button variant="outline" disabled={busy} onClick={() => action('scan')}>
              <RefreshCw />扫描 Episodes
            </Button>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.5fr_.7fr]">
          <Card className="instrument-card overflow-hidden">
            <CardHeader className="border-b border-border/70">
              <CardTitle>{batchWorker ? 'Batch Worker 控制台' : 'Collector 控制台'}</CardTitle>
              <CardDescription>
                {batchWorker
                  ? 'Studio 管理独立 RoboVerse 进程；生成结果保存后再进入统一扫描与 QA。'
                  : '统一入口内嵌当前引擎控制台；控制与视频仍直接连接对应 Worker。'}
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {running && session?.collector_url ? (
                <div className="space-y-3 p-3">
                  <iframe
                    className="h-[680px] w-full rounded-lg border border-border bg-black"
                    src={session.collector_url}
                    title={`${session.engine_id} collector`}
                    allow="serial; autoplay; fullscreen"
                  />
                  <Button
                    variant="outline"
                    render={<a href={session.collector_url} target="_blank" rel="noreferrer" />}
                  >
                    新标签页打开 Collector <ExternalLink />
                  </Button>
                </div>
              ) : (
                <div className="grid min-h-[480px] place-items-center bg-[radial-gradient(circle_at_center,var(--primary)/0.08,transparent_62%)] p-8 text-center">
                  <div className="max-w-md">
                  <div
                    className={`mx-auto mb-4 size-3 rounded-full ${
                      running
                        ? 'animate-pulse bg-emerald-400 shadow-[0_0_18px_#34d399]'
                        : 'bg-muted-foreground/40'
                    }`}
                  />
                  <h2 className="font-semibold">
                    {batchWorker
                      ? running ? 'Batch Worker 正在运行' : 'Batch Worker 尚未启动'
                      : running ? 'Collector 已启动' : 'Collector 尚未启动'}
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {running
                      ? batchWorker
                        ? 'RoboVerse 正在隔离环境中批量生成；完成后点击“扫描 Episodes”进入 QA。'
                        : '在新标签页打开实时画面。GELLO 模式下，在该页面选择串口并连接。'
                      : batchWorker
                        ? `启动后运行 ${session?.scene_id ?? 'ManiSkill'} 原生 scripted rollout；每条 Episode 保留官方 demo 轨迹与真实 source seed，完成后扫描进入 QA。`
                        : '启动前请确认 GPU 与端口空闲。启动不会自动打开串口或下发机器人动作。'}
                  </p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card className="instrument-card">
              <CardHeader>
                <CardTitle>采集进度</CardTitle>
                <CardDescription>扫描保存目录后更新</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <Progress value={Math.min(100, (count / target) * 100)}>
                  <ProgressLabel>Episodes</ProgressLabel>
                  <ProgressValue>{() => `${count} / ${target}`}</ProgressValue>
                </Progress>
                <div className="grid grid-cols-2 gap-2">
                  <Metric label="Accepted" value={session?.accepted_count ?? 0} />
                  <Metric label="Pending QA" value={session?.pending_count ?? 0} />
                </div>
                <Button
                  variant="outline"
                  className="w-full"
                  render={<a href={`/episodes?session=${sessionId}&engine=${session?.engine_id ?? ''}&qa=pending`} />}
                >
                  进入 QA 队列
                </Button>
              </CardContent>
            </Card>

            <Card className="instrument-card">
              <CardHeader>
                <CardTitle>Worker Runtime</CardTitle>
                <CardDescription>持久化运行身份与健康状态</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-xs leading-5">
                <RuntimeValue label="Run UUID" value={worker?.run_id ?? '—'} mono />
                <RuntimeValue label="Supervisor PID" value={worker?.supervisor_pid ?? '—'} mono />
                <RuntimeValue label="Child PID" value={worker?.child_pid ?? '—'} mono />
                <RuntimeValue label="Ready" value={formatRuntimeTime(worker?.ready_at)} />
                <RuntimeValue label="Heartbeat" value={formatRuntimeTime(worker?.heartbeat_at)} />
                <RuntimeValue label="Resources" value={worker?.resources?.join(' · ') || '—'} mono />
                {worker?.return_code != null && <RuntimeValue label="Return code" value={worker.return_code} mono />}
              </CardContent>
            </Card>

            <Card className="instrument-card">
              <CardHeader>
                <CardTitle>安全边界</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-xs leading-5 text-muted-foreground">
                <p>• 引擎、场景和控制来源均来自后端 allowlist。</p>
                <p>• 同一时间只运行一个 Studio 管理的仿真 Worker。</p>
                <p>• GELLO 限位、slew 和 watchdog 保留在引擎运行时。</p>
                {batchWorker && <p>• RoboVerse scripted batch 使用仿真 identity safety filter，不连接 GELLO 或真实硬件。</p>}
                {session?.engine_id === 'isaac_sim' && <p>• Isaac 空场景没有自动成功判据，保存为 unavailable。</p>}
                {worker?.log_path && <p className="break-all">• Log: {worker.log_path}</p>}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function formatRuntimeTime(value?: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

function RuntimeValue({ label, value, mono = false }: { label: string; value: string | number; mono?: boolean }) {
  return <div className="flex items-start justify-between gap-3 border-b border-border/60 pb-1"><span className="text-muted-foreground">{label}</span><span className={`max-w-52 break-all text-right ${mono ? 'font-mono' : ''}`}>{value}</span></div>;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border/70 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <strong className="mt-1 block font-mono text-xl">{value}</strong>
    </div>
  );
}
