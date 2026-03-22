'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Topbar from '@/components/topbar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { apiFetch, formatSize, formatTime, WS_BASE } from '@/lib/api';
import { STAGES, type Run, type LogEntry } from '@/lib/types';
import {
  Upload, Play, RefreshCw, CheckCircle2, Circle, Loader2,
  XCircle, RotateCcw, Pencil, ChevronRight
} from 'lucide-react';

type StepState = 'pending' | 'active' | 'complete' | 'failed';

interface AgentStep {
  key: string;
  label: string;
  agentName: string;
  summary: string;
  state: StepState;
}

export default function PipelinePage() {
  const [file, setFile] = useState<File | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [agents, setAgents] = useState<AgentStep[]>(
    STAGES.map(s => ({
      key: s.key,
      label: s.label,
      agentName: s.label.split(' — ')[1] || s.label.replace(/^[A-Z]\d\s*—?\s*/, '') + ' Agent',
      summary: '',
      state: 'pending' as StepState,
    }))
  );
  const [running, setRunning] = useState(false);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const addLog = useCallback((msg: string, type: LogEntry['type'] = 'default') => {
    setLogs(prev => [...prev, { time: formatTime(), message: msg, type }]);
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const data = await apiFetch<{ runs: Run[] }>('/runs');
      setRuns(data.runs || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const handleFiles = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f);
      addLog(`Selected: ${f.name} (${formatSize(f.size)})`, 'info');
    }
  }, [addLog]);

  const runPipeline = useCallback(async () => {
    if (!file) return;
    setRunning(true);
    setAgents(prev => prev.map(a => ({ ...a, state: 'pending', summary: '' })));
    addLog('Uploading RFP and starting pipeline…', 'info');

    try {
      const form = new FormData();
      form.append('file', file);
      const data = await apiFetch<{ run_id: string }>('/upload-rfp', {
        method: 'POST',
        headers: {},
        body: form,
      });
      addLog(`Pipeline started: ${data.run_id}`, 'success');
      setSelectedRun(data.run_id);

      const ws = new WebSocket(`${WS_BASE}/ws/pipeline/${data.run_id}`);
      wsRef.current = ws;

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.agent) {
            const idx = STAGES.findIndex(s => s.key === msg.agent);
            if (idx >= 0) {
              setAgents(prev => {
                const next = [...prev];
                for (let i = 0; i < idx; i++) {
                  next[i] = { ...next[i], state: 'complete' };
                }
                next[idx] = {
                  ...next[idx],
                  state: msg.status === 'done' ? 'complete' : msg.status === 'error' ? 'failed' : 'active',
                  summary: msg.summary || `${msg.status === 'done' ? 'Completed' : msg.status === 'error' ? 'Failed' : 'Processing'}…`,
                };
                return next;
              });
              addLog(`${STAGES[idx].label}: ${msg.status}`, msg.status === 'error' ? 'error' : 'success');
            }
          }
          if (msg.type === 'done') { setRunning(false); addLog('Pipeline complete!', 'success'); loadRuns(); }
          if (msg.type === 'error') { setRunning(false); addLog(`Failed: ${msg.detail}`, 'error'); }
        } catch { /* ignore */ }
      };
      ws.onerror = () => { addLog('WebSocket error', 'error'); setRunning(false); };
      ws.onclose = () => { setRunning(false); };
    } catch (e) {
      addLog(`Error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error');
      setRunning(false);
    }
  }, [file, addLog, loadRuns]);

  const timeAgo = (dateStr?: string) => {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  };

  return (
    <>
      <Topbar title="Pipeline" />
      <ScrollArea className="flex-1">
        <div className="p-6 space-y-5 max-w-6xl mx-auto w-full">

          {/* Top row: Upload + Pipeline Progress */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

            {/* RFP Upload */}
            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold">RFP Upload</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  className="flex flex-col items-center justify-center gap-3 p-10 rounded-lg
                             border-2 border-dashed border-border hover:border-muted-foreground/30
                             transition-colors cursor-pointer group"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input ref={fileInputRef} type="file" accept=".pdf" className="hidden" onChange={handleFiles} />
                  <Upload className="w-6 h-6 text-muted-foreground group-hover:text-foreground transition-colors" strokeWidth={1.5} />
                  <div className="text-center">
                    <p className="text-sm text-muted-foreground">Drop borde or drop zone.</p>
                    <p className="text-xs text-muted-foreground/70 mt-0.5">Drop to sant here.</p>
                  </div>
                </div>
                {file && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground bg-secondary rounded-md px-3 py-2">
                    <span className="font-medium text-foreground">{file.name}</span>
                    <span>({formatSize(file.size)})</span>
                  </div>
                )}
                <Button
                  onClick={runPipeline}
                  disabled={!file || running}
                  className="w-auto bg-primary hover:bg-primary/90 text-primary-foreground cursor-pointer"
                >
                  {running ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Play className="w-4 h-4 mr-2" />}
                  {running ? 'Running…' : 'Run Pipeline'}
                </Button>
              </CardContent>
            </Card>

            {/* Pipeline Progress */}
            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between w-full">
                  <CardTitle className="text-base font-semibold">Pipeline Progress</CardTitle>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" className="text-xs h-8 bg-primary/10 border-primary/30 text-primary hover:bg-primary/20 cursor-pointer">
                      <RotateCcw className="w-3 h-3 mr-1.5" /> Regenerate Stage
                    </Button>
                    <Button variant="outline" size="sm" className="text-xs h-8 bg-primary/10 border-primary/30 text-primary hover:bg-primary/20 cursor-pointer">
                      <Pencil className="w-3 h-3 mr-1.5" /> Edit Input
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-1">
                  {agents.slice(0, 6).map((agent, idx) => (
                    <div key={agent.key} className="flex items-start gap-3 py-2.5">
                      {/* Status icon */}
                      <div className="mt-0.5 shrink-0">
                        {agent.state === 'complete' ? (
                          <CheckCircle2 className="w-5 h-5 text-success" />
                        ) : agent.state === 'active' ? (
                          <Loader2 className="w-5 h-5 text-primary animate-spin" />
                        ) : agent.state === 'failed' ? (
                          <XCircle className="w-5 h-5 text-error" />
                        ) : (
                          <Circle className="w-5 h-5 text-muted-foreground/40" strokeWidth={1.5} />
                        )}
                      </div>
                      {/* Agent info */}
                      <div className="min-w-0">
                        <p className={`text-sm font-medium leading-none ${
                          agent.state === 'active' ? 'text-primary' :
                          agent.state === 'complete' ? 'text-foreground' :
                          'text-muted-foreground'
                        }`}>
                          {agent.agentName}
                        </p>
                        {agent.summary && (
                          <p className="text-xs text-muted-foreground mt-1">
                            Summary: {agent.summary}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Bottom row: Recent Runs + Agent Logs */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

            {/* Recent Runs */}
            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between w-full">
                  <CardTitle className="text-base font-semibold">Recent Runs</CardTitle>
                  <Button variant="ghost" size="icon" onClick={loadRuns} className="h-8 w-8 cursor-pointer">
                    <RefreshCw className="w-4 h-4 text-muted-foreground" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {runs.length === 0 ? (
                  <div className="text-center py-10 text-muted-foreground text-sm px-6">
                    No runs yet. Upload an RFP.
                  </div>
                ) : (
                  <div className="divide-y divide-border">
                    {runs.slice(0, 6).map(run => (
                      <div
                        key={run.run_id}
                        onClick={() => setSelectedRun(run.run_id)}
                        className={`flex items-center justify-between px-6 py-3 cursor-pointer 
                                   hover:bg-secondary/50 transition-colors ${
                                     selectedRun === run.run_id ? 'bg-secondary/50' : ''
                                   }`}
                      >
                        <div>
                          <p className="text-sm font-medium text-foreground">
                            {run.filename?.replace('.pdf', '') || `Run ${run.run_id.slice(0, 8)}`}
                          </p>
                          <p className="text-xs text-muted-foreground mt-0.5">{timeAgo(run.created_at)}</p>
                        </div>
                        <Badge
                          variant={run.status === 'FAILED' ? 'destructive' : 'secondary'}
                          className={`text-[10px] ${
                            run.status === 'FAILED' ? '' :
                            run.status === 'RUNNING' ? 'bg-warning/15 text-warning border-warning/30' :
                            'bg-success/15 text-success border-success/30'
                          }`}
                        >
                          {run.status === 'INTAKE_COMPLETE' || run.status === 'SUBMITTED' ? 'completed' : run.status.toLowerCase()}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Agent Logs */}
            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold">Agent Logs</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="bg-background/50 rounded-b-lg mx-3 mb-3 border border-border overflow-hidden">
                  <ScrollArea className="h-[250px]">
                    <div className="p-4 font-mono text-xs leading-relaxed space-y-0.5">
                      {logs.length === 0 ? (
                        <span className="text-muted-foreground italic">Waiting for pipeline activity…</span>
                      ) : (
                        logs.map((entry, i) => (
                          <div key={i} className="flex gap-2">
                            <span className="text-muted-foreground shrink-0">[{entry.time}]</span>
                            <span className={
                              entry.type === 'success' ? 'text-success' :
                              entry.type === 'error' ? 'text-error' :
                              entry.type === 'info' ? 'text-info' :
                              'text-muted-foreground'
                            }>
                              {entry.message}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </ScrollArea>
                </div>
              </CardContent>
            </Card>
          </div>

        </div>
      </ScrollArea>
    </>
  );
}
