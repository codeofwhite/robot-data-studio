'use client';

import { useCallback, useEffect, useState } from 'react';
import { Box, Database, FileArchive, RefreshCw } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/api';
import type { ExportJob, Session } from '@/lib/types';

const formats = [
  { id: 'lerobot', title: 'LeRobot v3', note: 'Parquet + MP4/images，适合主流 VLA 数据管线', icon: Box },
  { id: 'rlds', title: 'RLDS', note: 'TensorFlow Datasets episode/step 结构', icon: Database },
  { id: 'robomimic', title: 'Robomimic HDF5', note: 'HDF5 demos、mask 与相机观测', icon: FileArchive },
] as const;

export default function ExportsPage() {
  const [sessions, setSessions] = useState<Session[]>([]); const [jobs, setJobs] = useState<ExportJob[]>([]); const [datasetId, setDatasetId] = useState(''); const [format, setFormat] = useState<'lerobot' | 'rlds' | 'robomimic'>('lerobot'); const [name, setName] = useState('dataset_v1'); const [error, setError] = useState<string>(); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { try { const [nextSessions, nextJobs] = await Promise.all([api<Session[]>('/sessions'), api<ExportJob[]>('/exports')]); setSessions(nextSessions); setJobs(nextJobs); if (!datasetId && nextSessions[0]) setDatasetId(String(nextSessions[0].dataset_id)); setError(undefined); } catch (caught) { setError(caught instanceof Error ? caught.message : '加载失败'); } }, [datasetId]);
  useEffect(() => { void load(); }, [load]);
  async function start() { setBusy(true); try { await api('/exports', { method: 'POST', body: JSON.stringify({ dataset_id: Number(datasetId), format, output_name: name, repo_id: format === 'lerobot' ? `local/${name}` : null }) }); await load(); } catch (caught) { setError(caught instanceof Error ? caught.message : '导出失败'); } finally { setBusy(false); } }
  return <AppShell current="exports"><div className="space-y-5"><div><Badge variant="outline" className="mb-3">TRAINING FORMATS</Badge><h1 className="text-2xl font-semibold">导出中心</h1><p className="mt-1 text-sm text-muted-foreground">原始数据保持不变，按训练生态生成派生数据集。</p></div>{error && <div className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">{error}</div>}<div className="grid gap-3 md:grid-cols-3">{formats.map((item) => { const Icon = item.icon; const active = format === item.id; return <button key={item.id} onClick={() => setFormat(item.id)} className={`rounded-xl border p-4 text-left transition-colors ${active ? 'border-primary bg-primary/8' : 'border-border/70 bg-card hover:border-primary/40'}`}><Icon className={active ? 'size-5 text-primary' : 'size-5 text-muted-foreground'} /><strong className="mt-4 block">{item.title}</strong><span className="mt-1 block text-xs leading-5 text-muted-foreground">{item.note}</span></button>; })}</div><Card className="instrument-card"><CardHeader><CardTitle>新建导出任务</CardTitle><CardDescription>导出由 allowlist 命令异步执行，日志保存在 dataset/exports。</CardDescription></CardHeader><CardContent className="grid items-end gap-4 md:grid-cols-[1fr_1fr_auto]"><div className="space-y-2"><Label>Dataset</Label><NativeSelect className="w-full" value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{sessions.map((session) => <NativeSelectOption key={session.dataset_id} value={session.dataset_id}>{session.dataset_name ?? session.dataset_id}</NativeSelectOption>)}</NativeSelect></div><div className="space-y-2"><Label>输出名称</Label><Input value={name} onChange={(event) => setName(event.target.value)} /></div><Button disabled={busy || !datasetId || !name} onClick={start}>{busy ? '提交中…' : `导出 ${format}`}</Button></CardContent></Card><Card className="instrument-card"><CardHeader><CardTitle>任务记录</CardTitle><CardDescription>依赖不完整时保留失败状态和日志，不会伪装成功。</CardDescription></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>Job</TableHead><TableHead>Format</TableHead><TableHead>Status</TableHead><TableHead>Output</TableHead><TableHead><Button variant="ghost" size="sm" onClick={load}><RefreshCw /></Button></TableHead></TableRow></TableHeader><TableBody>{jobs.map((job) => <TableRow key={job.id}><TableCell className="font-mono text-xs">{job.id}</TableCell><TableCell>{job.format}</TableCell><TableCell><Badge variant={job.status === 'completed' ? 'default' : 'outline'}>{job.status}</Badge></TableCell><TableCell className="max-w-sm truncate font-mono text-xs">{job.output_path}</TableCell><TableCell className="text-xs text-destructive">{job.error}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card></div></AppShell>;
}
