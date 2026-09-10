'use client';

import { useCallback, useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import { Check, Database, RefreshCw, X } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/api';
import { engineLabel } from '@/lib/engines';
import type { Dataset, Episode } from '@/lib/types';

type QaFilter = 'all' | 'pending' | 'accepted' | 'rejected';
type EngineFilter = 'all' | 'genesis' | 'isaac_sim' | 'roboverse';

export default function EpisodesPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [qaFilter, setQaFilter] = useState<QaFilter>('all');
  const [engineFilter, setEngineFilter] = useState<EngineFilter>('all');
  const [datasetId, setDatasetId] = useState('all');
  const [sessionId, setSessionId] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [qaBusy, setQaBusy] = useState<number | null>(null);
  const [error, setError] = useState<string>();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setSessionId(params.get('session') ?? undefined);
    const requestedEngine = params.get('engine');
    if (requestedEngine === 'genesis' || requestedEngine === 'isaac_sim' || requestedEngine === 'roboverse') setEngineFilter(requestedEngine);
    const requestedQa = params.get('qa');
    if (requestedQa === 'pending' || requestedQa === 'accepted' || requestedQa === 'rejected') setQaFilter(requestedQa);
    const requestedDataset = params.get('dataset');
    if (requestedDataset) setDatasetId(requestedDataset);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams();
      if (sessionId) query.set('session_id', sessionId);
      if (!sessionId && datasetId !== 'all') query.set('dataset_id', datasetId);
      if (qaFilter !== 'all') query.set('qa_status', qaFilter);
      if (engineFilter !== 'all') query.set('engine_id', engineFilter);
      const [nextEpisodes, nextDatasets] = await Promise.all([
        api<Episode[]>(`/episodes?${query}`),
        api<Dataset[]>('/datasets'),
      ]);
      setEpisodes(nextEpisodes);
      setDatasets(nextDatasets);
      setError(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [datasetId, engineFilter, qaFilter, sessionId]);

  useEffect(() => { void load(); }, [load]);

  async function decide(event: MouseEvent, episode: Episode, qaStatus: 'accepted' | 'rejected') {
    event.stopPropagation();
    setQaBusy(episode.id);
    try {
      await api(`/episodes/${episode.id}/qa`, {
        method: 'PATCH',
        body: JSON.stringify({
          qa_status: qaStatus,
          failure_reason: qaStatus === 'rejected' ? episode.failure_reason ?? 'quick_reject' : null,
        }),
      });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'QA 更新失败');
    } finally {
      setQaBusy(null);
    }
  }

  return (
    <AppShell current="episodes">
      <div className="space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Badge variant="outline" className="mb-3">DATASET QA</Badge>
            <h1 className="text-2xl font-semibold">Episodes</h1>
            <p className="mt-1 text-sm text-muted-foreground">按 Dataset、Simulator 和 QA 状态建立清晰的审核队列。</p>
          </div>
          <Button variant="outline" onClick={load}><RefreshCw className={loading ? 'animate-spin' : ''} />刷新</Button>
        </div>

        {error && <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>}

        <Card className="instrument-card">
          <CardHeader>
            <CardTitle>Episode 索引</CardTitle>
            <CardDescription>{sessionId ? `Session 队列：${sessionId}` : `${episodes.length} 条记录`}</CardDescription>
            <div className="grid gap-2 pt-2 sm:grid-cols-3">
              <NativeSelect value={datasetId} disabled={Boolean(sessionId)} onChange={(event) => setDatasetId(event.target.value)}>
                <NativeSelectOption value="all">全部 Dataset</NativeSelectOption>
                {datasets.map((dataset) => <NativeSelectOption key={dataset.id} value={dataset.id}>{dataset.name}</NativeSelectOption>)}
              </NativeSelect>
              <NativeSelect value={engineFilter} onChange={(event) => setEngineFilter(event.target.value as EngineFilter)}>
                <NativeSelectOption value="all">全部 Simulator</NativeSelectOption>
                <NativeSelectOption value="genesis">Genesis</NativeSelectOption>
                <NativeSelectOption value="isaac_sim">Isaac Sim</NativeSelectOption>
                <NativeSelectOption value="roboverse">RoboVerse</NativeSelectOption>
              </NativeSelect>
              <NativeSelect value={qaFilter} onChange={(event) => setQaFilter(event.target.value as QaFilter)}>
                <NativeSelectOption value="all">全部 QA 状态</NativeSelectOption>
                <NativeSelectOption value="pending">Pending</NativeSelectOption>
                <NativeSelectOption value="accepted">Accepted</NativeSelectOption>
                <NativeSelectOption value="rejected">Rejected</NativeSelectOption>
              </NativeSelect>
            </div>
          </CardHeader>
          <CardContent className="px-2 sm:px-4">
            {!loading && episodes.length === 0 ? (
              <Empty><EmptyHeader><EmptyMedia variant="icon"><Database /></EmptyMedia><EmptyTitle>当前队列没有 Episode</EmptyTitle><EmptyDescription>调整筛选条件，或在会话页扫描采集目录。</EmptyDescription></EmptyHeader><EmptyContent><Button render={<a href="/sessions/new" />}>新建采集会话</Button></EmptyContent></Empty>
            ) : (
              <Table>
                <TableHeader><TableRow><TableHead>Episode</TableHead><TableHead>Simulator</TableHead><TableHead>Scene / Task</TableHead><TableHead>Frames</TableHead><TableHead>Operator</TableHead><TableHead>Auto</TableHead><TableHead>QA</TableHead><TableHead>快捷 QA</TableHead></TableRow></TableHeader>
                <TableBody>{episodes.map((episode) => (
                  <TableRow key={episode.id} className="cursor-pointer" onClick={() => { window.location.href = `/episodes/${episode.id}`; }}>
                    <TableCell><p className="font-mono text-xs">#{String(episode.episode_index ?? '?').padStart(6, '0')}</p><p className="font-mono text-[10px] text-muted-foreground">{episode.episode_uuid.slice(0, 12)}</p></TableCell>
                    <TableCell><Badge variant="outline">{engineLabel(episode.engine_id)}</Badge><p className="mt-1 font-mono text-[10px] text-muted-foreground">{episode.engine_version ?? 'version N/A'}</p></TableCell>
                    <TableCell><p className="text-xs text-muted-foreground">{episode.scene_id} · {episode.control_mode}</p><p>{episode.task}</p></TableCell>
                    <TableCell className="font-mono text-xs">{episode.num_frames}<br /><span className="text-muted-foreground">{episode.duration_s?.toFixed(1) ?? 'N/A'} s</span></TableCell>
                    <TableCell><Result value={episode.operator_success == null ? null : Boolean(episode.operator_success)} /></TableCell>
                    <TableCell><Result value={episode.auto_success == null ? null : Boolean(episode.auto_success)} /></TableCell>
                    <TableCell><Badge variant={episode.qa_status === 'accepted' ? 'default' : 'outline'}>{episode.qa_status}</Badge></TableCell>
                    <TableCell><div className="flex gap-1"><Button size="sm" disabled={qaBusy === episode.id || episode.qa_status === 'accepted'} onClick={(event) => void decide(event, episode, 'accepted')}><Check />Accept</Button><Button size="sm" variant="outline" disabled={qaBusy === episode.id || episode.qa_status === 'rejected'} onClick={(event) => void decide(event, episode, 'rejected')}><X />Reject</Button></div></TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function Result({ value }: { value: boolean | null }) {
  return <span className={value == null ? 'text-xs text-muted-foreground' : value ? 'metric-ok text-xs' : 'metric-danger text-xs'}>{value == null ? 'N/A' : value ? 'SUCCESS' : 'FAILURE'}</span>;
}
