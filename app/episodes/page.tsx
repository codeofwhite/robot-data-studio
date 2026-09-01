'use client';

import { useCallback, useEffect, useState } from 'react';
import { Database, RefreshCw } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/api';
import type { Episode } from '@/lib/types';

export default function EpisodesPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]); const [filter, setFilter] = useState('all'); const [loading, setLoading] = useState(true); const [error, setError] = useState<string>();
  const load = useCallback(async () => { setLoading(true); try { const params = new URLSearchParams(window.location.search); const session = params.get('session'); const query = new URLSearchParams(); if (session) query.set('session_id', session); if (filter !== 'all') query.set('qa_status', filter); setEpisodes(await api<Episode[]>(`/episodes?${query}`)); setError(undefined); } catch (caught) { setError(caught instanceof Error ? caught.message : '加载失败'); } finally { setLoading(false); } }, [filter]);
  useEffect(() => { void load(); }, [load]);
  return <AppShell current="episodes"><div className="space-y-5"><div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><Badge variant="outline" className="mb-3">DATASET QA</Badge><h1 className="text-2xl font-semibold">Episodes</h1><p className="mt-1 text-sm text-muted-foreground">自动成功、操作员结果和人工 QA 独立展示。</p></div><div className="flex gap-2"><NativeSelect value={filter} onChange={(event) => setFilter(event.target.value)}><NativeSelectOption value="all">全部 QA 状态</NativeSelectOption><NativeSelectOption value="pending">Pending</NativeSelectOption><NativeSelectOption value="accepted">Accepted</NativeSelectOption><NativeSelectOption value="rejected">Rejected</NativeSelectOption></NativeSelect><Button variant="outline" onClick={load}><RefreshCw className={loading ? 'animate-spin' : ''} />刷新</Button></div></div>{error && <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>}<Card className="instrument-card"><CardHeader><CardTitle>Episode 索引</CardTitle><CardDescription>{episodes.length} 条记录</CardDescription></CardHeader><CardContent className="px-2 sm:px-4">{!loading && episodes.length === 0 ? <Empty><EmptyHeader><EmptyMedia variant="icon"><Database /></EmptyMedia><EmptyTitle>还没有 Episode</EmptyTitle><EmptyDescription>在会话页扫描采集目录，完成的数据会出现在这里。</EmptyDescription></EmptyHeader><EmptyContent><Button render={<a href="/sessions/new" />}>新建采集会话</Button></EmptyContent></Empty> : <Table><TableHeader><TableRow><TableHead>UUID</TableHead><TableHead>Task</TableHead><TableHead>Frames</TableHead><TableHead>Operator</TableHead><TableHead>Auto</TableHead><TableHead>QA</TableHead></TableRow></TableHeader><TableBody>{episodes.map((episode) => <TableRow key={episode.id} className="cursor-pointer" onClick={() => { window.location.href = `/episodes/${episode.id}`; }}><TableCell className="font-mono text-xs">{episode.episode_uuid.slice(0, 12)}</TableCell><TableCell>{episode.task}</TableCell><TableCell className="font-mono">{episode.num_frames}</TableCell><TableCell><Result value={episode.operator_success == null ? null : Boolean(episode.operator_success)} /></TableCell><TableCell><Result value={episode.auto_success == null ? null : Boolean(episode.auto_success)} /></TableCell><TableCell><Badge variant={episode.qa_status === 'accepted' ? 'default' : 'outline'}>{episode.qa_status}</Badge></TableCell></TableRow>)}</TableBody></Table>}</CardContent></Card></div></AppShell>;
}
function Result({ value }: { value: boolean | null }) { return <span className={value == null ? 'text-xs text-muted-foreground' : value ? 'metric-ok text-xs' : 'metric-danger text-xs'}>{value == null ? 'N/A' : value ? 'SUCCESS' : 'FAILURE'}</span>; }
