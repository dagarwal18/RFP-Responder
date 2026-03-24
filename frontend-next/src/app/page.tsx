'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Topbar from '@/components/topbar';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { apiFetch, fetchRuns, uploadRfp, formatSize, formatTime, WS_BASE } from '@/lib/api';
import { STAGES, type Run, type LogEntry } from '@/lib/types';
import { Upload, Play, RefreshCw, Loader2 } from 'lucide-react';
import CheckpointsPanel from '@/components/checkpoints-panel';
import AgentOutputs from '@/components/agent-outputs';

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
      const data = await fetchRuns();
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

  const [selectedRunStatus, setSelectedRunStatus] = useState<any>(null);

  const connectWS = useCallback((rfpId: string) => {
    setRunning(true);
    const ws = new WebSocket(`${WS_BASE}/api/rfp/ws/${rfpId}`);
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
  }, [addLog, loadRuns]);

  const viewRun = useCallback(async (rfpId: string) => {
    setSelectedRun(rfpId);
    try {
      const status = await apiFetch<any>(`/api/rfp/${rfpId}/status`);
      setSelectedRunStatus(status);
      addLog(`Viewing run ${rfpId}: ${status.status}`, 'info');

      // Update stepper based on status
      const currentAgent = status.current_agent || '';
      const isFailed = status.status === 'FAILED';
      let hitCurrent = false;

      setAgents(prev => prev.map(a => {
        if (a.key === currentAgent) {
          hitCurrent = true;
          return { ...a, state: isFailed ? 'failed' : 'active', summary: '' };
        } else if (!hitCurrent && currentAgent) {
          return { ...a, state: 'complete', summary: '' };
        }
        return { ...a, state: 'pending', summary: '' };
      }));

      if (status.status === 'RUNNING') {
        connectWS(rfpId);
      }
    } catch (e: any) {
      addLog(`Failed to load run: ${e.message}`, 'error');
    }
  }, [addLog, connectWS]);

  const runPipeline = useCallback(async () => {
    if (!file) return;
    setRunning(true);
    setAgents(prev => prev.map(a => ({ ...a, state: 'pending', summary: '' })));
    setSelectedRunStatus(null);
    addLog('Uploading RFP and starting pipeline…', 'info');

    try {
      const form = new FormData();
      form.append('file', file);
      const data = await uploadRfp(form);
      addLog(`Pipeline started: ${data.run_id}`, 'success');
      setSelectedRun(data.run_id);

      if (data.status === 'COMPLETED' || data.status === 'SUBMITTED' || data.status === 'REJECTED') {
         viewRun(data.run_id);
         setRunning(false);
         loadRuns();
      } else {
         connectWS(data.run_id);
      }
    } catch (e) {
      addLog(`Error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error');
      setRunning(false);
    }
  }, [file, addLog, loadRuns, connectWS, viewRun]);

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
    <div className="flex flex-1 h-full overflow-hidden bg-background">
      {/* MAIN WORKSPACE ZONE */}
      <div className="flex-1 flex flex-col min-w-0 border-r border-border relative">
        <Topbar title="Workspace" />
        <ScrollArea className="flex-1">
          <div className="flex flex-col">
            
            {/* Upload Strip */}
            <div 
              className="px-8 py-6 border-b border-border flex items-center justify-between group cursor-pointer hover:bg-muted/10 transition-colors duration-100 ease-linear" 
              onClick={() => fileInputRef.current?.click()}
            >
              <input ref={fileInputRef} type="file" accept=".pdf" className="hidden" onChange={handleFiles} />
              <div className="flex flex-col">
                <span className="text-[14px] font-medium text-foreground tracking-tight">Upload Document</span>
                <span className="text-[13px] text-muted-foreground mt-1.5">Select an RFP PDF to initiate a new analysis pipeline.</span>
                {file && (
                  <div className="flex items-center gap-3 mt-4 text-[13px] text-muted-foreground border-l-2 border-primary pl-3 bg-secondary/50 py-2">
                    <span className="font-medium text-foreground">{file.name}</span>
                    <span>{formatSize(file.size)}</span>
                  </div>
                )}
              </div>
              <Button 
                onClick={(e) => { e.stopPropagation(); runPipeline(); }}
                disabled={!file || running}
                className="bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-6 text-[13px] font-medium shrink-0 ml-6 cursor-pointer"
              >
                {running ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Play className="w-4 h-4 mr-2" />}
                {running ? 'Processing' : 'Run Pipeline'}
              </Button>
            </div>

            {/* Pipeline Timeline */}
            <div className="p-8 border-b border-border">
              <div className="flex items-center justify-between mb-8">
                <h2 className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em]">Pipeline Flow</h2>
                <div className="flex gap-5">
                  <span className="text-[12px] text-primary cursor-pointer hover:underline underline-offset-4">Regenerate Stage</span>
                  <span className="text-[12px] text-primary cursor-pointer hover:underline underline-offset-4">Edit Input</span>
                </div>
              </div>
              
              <div className="flex flex-col pl-2">
                {agents.map((agent, idx) => (
                  <div key={agent.key} className={`flex items-start gap-6 relative ${agent.state === 'active' || agent.state === 'complete' ? 'opacity-100' : 'opacity-40'} pb-7 last:pb-0`}>
                    <div className="relative flex flex-col items-center mt-1">
                      <div className={`w-2 h-2 shrink-0 ${agent.state === 'active' ? 'bg-primary' : agent.state === 'complete' ? 'bg-success' : agent.state === 'failed' ? 'bg-error' : 'bg-muted'}`} />
                      {idx !== agents.length - 1 && (
                          <div className="w-[1px] bg-border absolute top-2 bottom-[-28px]" />
                      )}
                    </div>
                    <div className="min-w-0">
                      <p className={`text-[14px] font-medium leading-none ${agent.state === 'active' ? 'text-primary' : 'text-foreground'}`}>
                        {agent.agentName}
                      </p>
                      <p className="text-[13px] text-muted-foreground mt-2.5">
                        {agent.summary || (agent.state === 'pending' ? 'Awaiting parameter injection...' : 'Processing execution subroutines...')}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Run Details (Checkpoints & Outputs) */}
            {selectedRun && selectedRunStatus && (
              <div className="flex flex-col border-b border-border">
                 <CheckpointsPanel rfpId={selectedRun} onRerun={(id) => { viewRun(id); loadRuns(); }} />
                 <AgentOutputs outputs={selectedRunStatus.agent_outputs || {}} />
              </div>
            )}

            {/* Recent Runs List */}
            <div className="p-8">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em]">Recent Executions</h2>
                <RefreshCw className="w-3.5 h-3.5 text-muted-foreground cursor-pointer hover:text-foreground transition-colors" onClick={loadRuns} />
              </div>
              
              <div className="flex flex-col border-t border-border w-full">
                {runs.length === 0 ? (
                  <div className="text-[13px] text-muted-foreground py-6">No historical runs associated with this workspace.</div>
                ) : (
                  runs.slice(0, 10).map(run => (
                    <div key={run.run_id} onClick={() => viewRun(run.run_id)} className={`flex items-center justify-between py-4 border-b border-border cursor-pointer hover:bg-muted/10 transition-colors duration-100 ease-linear ${selectedRun === run.run_id ? 'bg-muted/10' : ''}`}>
                      <div className="pl-4">
                        <p className="text-[13px] font-medium text-foreground">{run.filename?.replace('.pdf', '') || `Execution ${run.run_id.slice(0, 8)}`}</p>
                        <p className="text-[12px] text-muted-foreground mt-1.5">{timeAgo(run.created_at)}</p>
                      </div>
                      <div className="pr-4">
                        <span className={`text-[10px] uppercase tracking-wider font-semibold ${run.status === 'FAILED' ? 'text-error' : run.status === 'RUNNING' ? 'text-primary' : 'text-success'}`}>
                          {run.status === 'INTAKE_COMPLETE' || run.status === 'SUBMITTED' ? 'COMPLETED' : run.status}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

          </div>
        </ScrollArea>
      </div>

      {/* RIGHT CONTEXT ZONE */}
      <div className="w-[360px] min-w-[360px] max-w-[360px] shrink-0 bg-sidebar flex flex-col z-10 border-l border-border">
        <div className="h-14 border-b border-border flex items-center px-6 shrink-0 bg-background/50">
          <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em]">Console Stream</span>
        </div>
        <div className="flex-1 overflow-y-auto p-6 font-mono text-[11px] leading-[1.6] text-muted-foreground space-y-2 break-all whitespace-pre-wrap">
          {logs.length === 0 ? (
            <span className="opacity-40">Listening for pipeline execution...</span>
          ) : (
            logs.map((entry, i) => (
              <div key={i} className="flex gap-3">
                <span className="opacity-40 shrink-0">[{entry.time}]</span>
                <span className={
                  entry.type === 'success' ? 'text-success' :
                  entry.type === 'error' ? 'text-error' :
                  entry.type === 'info' ? 'text-foreground' :
                  'text-muted-foreground'
                }>
                  {entry.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
