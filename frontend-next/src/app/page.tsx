'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Topbar from '@/components/topbar';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  apiFetch,
  fetchRunStatus,
  fetchRuns,
  formatSize,
  formatTime,
  normalizeStageKey,
  uploadRfp,
  WS_BASE,
} from '@/lib/api';
import { STAGES, type Run, type LogEntry } from '@/lib/types';
import { Play, RefreshCw, Loader2 } from 'lucide-react';
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

// Estimated duration per agent in seconds (based on observed pipeline runs)
const AGENT_ESTIMATED_SECONDS: Record<string, number> = {
  A1_INTAKE: 35,
  A2_STRUCTURING: 25,
  A3_GO_NO_GO: 30,
  B1_REQUIREMENTS_EXTRACTION: 45,
  B2_REQUIREMENTS_VALIDATION: 50,
  C1_ARCHITECTURE_PLANNING: 20,
  C2_REQUIREMENT_WRITING: 120,
  C3_NARRATIVE_ASSEMBLY: 60,
  D1_TECHNICAL_VALIDATION: 40,
  E1_COMMERCIAL: 15,
  E2_LEGAL: 15,
  H1_HUMAN_VALIDATION: 10,
  F1_FINAL_READINESS: 15,
};

const AGENT_ACTIVE_TEXT: Record<string, string> = {
  A1_INTAKE: 'Parsing document and extracting tables via VLM...',
  A2_STRUCTURING: 'Classifying sections into semantic categories...',
  A3_GO_NO_GO: 'Evaluating strategic fit and compliance risk...',
  B1_REQUIREMENTS_EXTRACTION: 'Extracting and de-duplicating requirements...',
  B2_REQUIREMENTS_VALIDATION: 'Validating requirements against source document...',
  C1_ARCHITECTURE_PLANNING: 'Building response architecture and section plan...',
  C2_REQUIREMENT_WRITING: 'Drafting section responses with compliance matrix...',
  C3_NARRATIVE_ASSEMBLY: 'Assembling executive summary and full narrative...',
  D1_TECHNICAL_VALIDATION: 'Running completeness and alignment checks...',
  E1_COMMERCIAL: 'Reviewing pricing and commercial terms...',
  E2_LEGAL: 'Scanning for legal risks and certifications...',
  H1_HUMAN_VALIDATION: 'Preparing review package for human approval...',
  F1_FINAL_READINESS: 'Compiling final submission package...',
};

const AGENT_COMPLETE_TEXT: Record<string, string> = {
  A1_INTAKE: 'Document parsed and tables extracted',
  A2_STRUCTURING: 'Sections classified into categories',
  A3_GO_NO_GO: 'Strategic fit and compliance assessed',
  B1_REQUIREMENTS_EXTRACTION: 'Requirements extracted and de-duplicated',
  B2_REQUIREMENTS_VALIDATION: 'Requirements validated against source',
  C1_ARCHITECTURE_PLANNING: 'Response architecture and section plan built',
  C2_REQUIREMENT_WRITING: 'Section responses drafted with coverage matrix',
  C3_NARRATIVE_ASSEMBLY: 'Executive summary and narrative assembled',
  D1_TECHNICAL_VALIDATION: 'Completeness and alignment checks passed',
  E1_COMMERCIAL: 'Pricing and commercial terms reviewed',
  E2_LEGAL: 'Legal risks and certifications scanned',
  H1_HUMAN_VALIDATION: 'Review package prepared for approval',
  F1_FINAL_READINESS: 'Final submission package compiled',
};

const COMPLETE_TERMINAL_STATUSES = [
  'AWAITING_HUMAN_VALIDATION',
  'REJECTED',
  'SUBMITTED',
  'COMPLETED',
];

function resolveStageKeys(agentName: string | null | undefined): string[] {
  const raw = String(agentName || '').trim();
  if (!raw) return [];
  if (raw === 'COMMERCIAL_LEGAL_PARALLEL' || raw === 'commercial_legal_parallel') {
    return ['E1_COMMERCIAL', 'E2_LEGAL'];
  }
  const normalized = normalizeStageKey(raw);
  return normalized ? [normalized] : [];
}

function buildInitialAgents(): AgentStep[] {
  const agentNames: Record<string, string> = {
    A1_INTAKE: 'Intake Agent',
    A2_STRUCTURING: 'Structuring Agent',
    A3_GO_NO_GO: 'Go / No-Go Agent',
    B1_REQUIREMENTS_EXTRACTION: 'Requirements Extraction Agent',
    B2_REQUIREMENTS_VALIDATION: 'Requirements Validation Agent',
    C1_ARCHITECTURE_PLANNING: 'Architecture Planning Agent',
    C2_REQUIREMENT_WRITING: 'Requirement Writing Agent',
    C3_NARRATIVE_ASSEMBLY: 'Narrative Assembly Agent',
    D1_TECHNICAL_VALIDATION: 'Technical Validation Agent',
    E1_COMMERCIAL: 'Commercial Review Agent',
    E2_LEGAL: 'Legal Review Agent',
    H1_HUMAN_VALIDATION: 'Human Validation Agent',
    F1_FINAL_READINESS: 'Final Readiness Agent',
  };
  return STAGES.map((stage) => ({
    key: stage.key,
    label: stage.label,
    agentName: agentNames[stage.key] || `${stage.key} Agent`,
    summary: '',
    state: 'pending',
  }));
}

/* ── Per-agent progress bar timeline ──────────────────── */

function PipelineTimeline({ agents }: { agents: AgentStep[] }) {
  const startTimesRef = useRef<Record<string, number>>({});
  const [tick, setTick] = useState(0);

  // Track when each agent becomes active
  useEffect(() => {
    for (const agent of agents) {
      if (agent.state === 'active' && !startTimesRef.current[agent.key]) {
        startTimesRef.current[agent.key] = Date.now();
      }
      if (agent.state !== 'active') {
        delete startTimesRef.current[agent.key];
      }
    }
  }, [agents]);

  // Tick every 500ms to smoothly update progress
  const hasActive = agents.some(a => a.state === 'active');
  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(() => setTick(t => t + 1), 500);
    return () => clearInterval(id);
  }, [hasActive]);

  const getProgress = (key: string): number => {
    const start = startTimesRef.current[key];
    if (!start) return 0;
    const elapsed = (Date.now() - start) / 1000;
    const estimated = AGENT_ESTIMATED_SECONDS[key] || 30;
    // Asymptotic curve: reaches ~85% at estimated time,
    // then keeps slowly creeping toward 99% — never stalls.
    const ratio = elapsed / estimated;
    const progress = 100 * (1 - Math.exp(-1.9 * ratio));
    return Math.min(Math.round(progress), 99);
  };

  // Compute overall pipeline progress
  const completedCount = agents.filter(a => a.state === 'complete').length;
  const activeProgress = agents.reduce((acc, a) => {
    if (a.state === 'active') return acc + getProgress(a.key) / 100;
    return acc;
  }, 0);
  const overallPercent = Math.round(((completedCount + activeProgress) / agents.length) * 100);

  // Suppress unused tick warning
  void tick;

  return (
    <div className="p-8 border-b border-border">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em]">Pipeline Flow</h2>
        {hasActive && (
          <span className="text-[12px] font-semibold text-primary">{overallPercent}% complete</span>
        )}
        {!hasActive && completedCount > 0 && (
          <span className="text-[12px] font-semibold text-success">{overallPercent}% complete</span>
        )}
      </div>

      {/* Overall progress bar */}
      {(hasActive || completedCount > 0) && (
        <div className="h-[3px] w-full bg-muted overflow-hidden mb-8">
          <div
            className={`h-full transition-all duration-500 ease-out ${completedCount === agents.length ? 'bg-success' : 'bg-primary'}`}
            style={{ width: `${overallPercent}%` }}
          />
        </div>
      )}
      {!hasActive && completedCount === 0 && <div className="mb-8" />}

      <div className="flex flex-col pl-2">
        {agents.map((agent, idx) => {
          const pct = agent.state === 'active' ? getProgress(agent.key) : agent.state === 'complete' ? 100 : 0;
          return (
            <div key={agent.key} className={`flex items-start gap-6 relative ${agent.state === 'active' || agent.state === 'complete' ? 'opacity-100' : 'opacity-40'} pb-7 last:pb-0`}>
              <div className="relative flex flex-col items-center mt-1">
                <div className={`w-2 h-2 shrink-0 ${agent.state === 'active' ? 'bg-primary animate-pulse' : agent.state === 'complete' ? 'bg-success' : agent.state === 'failed' ? 'bg-error' : 'bg-muted'}`} />
                {idx !== agents.length - 1 && (
                  <div className={`w-[1px] absolute top-2 bottom-[-28px] ${agent.state === 'complete' ? 'bg-success/40' : 'bg-border'}`} />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <p className={`text-[14px] font-medium leading-none ${agent.state === 'active' ? 'text-primary' : 'text-foreground'}`}>
                    {agent.agentName}
                  </p>
                  {(agent.state === 'active' || agent.state === 'complete') && (
                    <span className={`text-[11px] font-semibold tabular-nums ${agent.state === 'complete' ? 'text-success' : 'text-primary'}`}>
                      {pct}%
                    </span>
                  )}
                </div>
                <p className={`text-[13px] mt-2 ${agent.state === 'failed' ? 'text-error' : 'text-muted-foreground'}`}>
                  {agent.summary
                    || (agent.state === 'complete' ? (AGENT_COMPLETE_TEXT[agent.key] || 'Completed')
                      : agent.state === 'active' ? (AGENT_ACTIVE_TEXT[agent.key] || 'Processing...')
                        : agent.state === 'failed' ? 'Failed'
                          : 'Awaiting parameter injection...')}
                </p>
                {(agent.state === 'active' || agent.state === 'complete') && (
                  <div className="mt-2 h-[3px] w-full bg-muted overflow-hidden">
                    <div
                      className={`h-full transition-all duration-500 ease-out ${agent.state === 'complete' ? 'bg-success' : 'bg-primary'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


export default function PipelinePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [file, setFile] = useState<File | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [agents, setAgents] = useState<AgentStep[]>(buildInitialAgents);
  const [running, setRunning] = useState(false);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [selectedRunStatus, setSelectedRunStatus] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const selectedRunRef = useRef<string | null>(null);

  const addLog = useCallback((msg: string, type: LogEntry['type'] = 'default') => {
    setLogs(prev => [...prev, { time: formatTime(), message: msg, type }]);
  }, []);

  const resetAgents = useCallback(() => {
    setAgents(buildInitialAgents());
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const data = await fetchRuns();
      setRuns(data.runs || []);
    } catch { /* ignore */ }
  }, []);

  const applyRunStatusToStepper = useCallback((status: any) => {
    const currentAgents = resolveStageKeys(status?.current_agent);
    const runStatus = String(status?.status || '').toUpperCase();
    const isCompleteTerminal = COMPLETE_TERMINAL_STATUSES.includes(runStatus);
    const isFailed = runStatus === 'FAILED';

    setAgents((prev) => {
      if (isCompleteTerminal) {
        return prev.map((agent) => ({
          ...agent,
          state: 'complete',
          summary: '',
        }));
      }

      // If pipeline is in a failed terminal state and there's no current_agent,
      // mark everything failed so the timeline stops showing an in-progress state.
      if (currentAgents.length === 0 && isFailed) {
        return prev.map((agent) => ({
          ...agent,
          state: 'failed',
          summary: '',
        }));
      }

      let hitCurrent = false;
      return prev.map((agent) => {
        if (currentAgents.includes(agent.key)) {
          hitCurrent = true;
          return {
            ...agent,
            state: isFailed ? 'failed' : 'active',
            summary: '',
          };
        }
        // Agents before the current one → complete
        if (!hitCurrent && currentAgents.length > 0) {
          return { ...agent, state: 'complete', summary: '' };
        }
        return { ...agent, state: 'pending', summary: '' };
      });
    });
  }, []);

  const loadRun = useCallback(async (rfpId: string) => {
    const status = await fetchRunStatus(rfpId);
    setSelectedRun(rfpId);
    setSelectedRunStatus(status);
    setRunning(status.status === 'RUNNING');
    applyRunStatusToStepper(status);
    return status;
  }, [applyRunStatusToStepper]);

  useEffect(() => { loadRuns(); }, [loadRuns]);
  useEffect(() => { selectedRunRef.current = selectedRun; }, [selectedRun]);

  const handleFiles = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f);
      addLog(`Selected: ${f.name} (${formatSize(f.size)})`, 'info');
    }
  }, [addLog]);

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
                summary: msg.summary || `${msg.status === 'done' ? 'Completed' : msg.status === 'error' ? 'Failed' : 'Processing'}â€¦`,
              };
              return next;
            });
            addLog(`${STAGES[idx].label}: ${msg.status}`, msg.status === 'error' ? 'error' : 'success');
          }
        }
        if (msg.type === 'done') {
          setRunning(false);
          addLog('Pipeline complete!', 'success');
          loadRuns();
          fetchRunStatus(rfpId).then((status) => {
            setSelectedRun(rfpId);
            setSelectedRunStatus(status);
            applyRunStatusToStepper(status);
          }).catch(() => { });
        }
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
      applyRunStatusToStepper(status);

      if (status.status === 'RUNNING') {
        connectWS(rfpId);
      }
    } catch (e: any) {
      addLog(`Failed to load run: ${e.message}`, 'error');
    }
  }, [addLog, applyRunStatusToStepper, connectWS]);

  void connectWS;
  void viewRun;

  const connectLiveUpdates = useCallback((rfpId: string) => {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
    }

    setRunning(true);
    const ws = new WebSocket(`${WS_BASE}/api/rfp/ws/${rfpId}`);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        const event = msg.event;
        const stageKeys = resolveStageKeys(msg.agent);

        switch (event) {
          case 'node_start':
            if (stageKeys.length > 0) {
              setAgents((prev) => prev.map((agent) => (
                stageKeys.includes(agent.key)
                  ? { ...agent, state: 'active', summary: 'Processing execution subroutines...' }
                  : agent
              )));
            }
            addLog(`Starting ${msg.agent}`, 'info');
            break;

          case 'node_end':
            if (stageKeys.length > 0) {
              setAgents((prev) => prev.map((agent) => (
                stageKeys.includes(agent.key)
                  ? { ...agent, state: 'complete', summary: msg.status || 'Completed' }
                  : agent
              )));
            }
            addLog(`${msg.agent} -> ${msg.status || 'Completed'}`, 'success');
            if (!msg.is_history && String(msg.status || '').includes('AWAITING_HUMAN_VALIDATION')) {
              router.push(`/review?run_id=${rfpId}`);
            }
            break;

          case 'error':
            if (stageKeys.length > 0) {
              setAgents((prev) => prev.map((agent) => (
                stageKeys.includes(agent.key)
                  ? { ...agent, state: 'failed', summary: msg.message || 'Failed' }
                  : agent
              )));
            }
            addLog(`${msg.agent || 'SYSTEM'}: ${msg.message || 'Pipeline error'}`, 'error');
            setRunning(false);
            break;

          case 'pipeline_end':
            setRunning(false);
            addLog(`Pipeline finished: ${msg.status || 'UNKNOWN'}`, msg.status === 'FAILED' ? 'error' : 'success');
            loadRuns();
            fetchRunStatus(rfpId).then((status) => {
              setSelectedRun(rfpId);
              setSelectedRunStatus(status);
              applyRunStatusToStepper(status);
            }).catch(() => { });
            if (!msg.is_history && msg.status === 'AWAITING_HUMAN_VALIDATION') {
              router.push(`/review?run_id=${rfpId}`);
            }
            break;

          default:
            break;
        }
      } catch {
        /* ignore malformed messages */
      }
    };

    ws.onerror = () => {
      addLog('WebSocket error', 'error');
      setRunning(false);
    };

    ws.onclose = () => {
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
    };
  }, [addLog, applyRunStatusToStepper, loadRuns, router]);

  const openRun = useCallback(async (rfpId: string) => {
    try {
      const status = await loadRun(rfpId);
      addLog(`Viewing run ${rfpId}: ${status.status}`, 'info');
      if (status.status === 'RUNNING') {
        connectLiveUpdates(rfpId);
      }
    } catch (e: any) {
      addLog(`Failed to load run: ${e.message}`, 'error');
    }
  }, [addLog, connectLiveUpdates, loadRun]);

  useEffect(() => {
    const runId = searchParams.get('run_id');
    if (!runId || runId === selectedRunRef.current) return;
    openRun(runId);
  }, [openRun, searchParams]);

  useEffect(() => () => {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
    }
  }, []);

  const runPipeline = useCallback(async () => {
    if (!file) return;
    setRunning(true);
    resetAgents();
    setSelectedRunStatus(null);
    addLog('Uploading RFP and starting pipelineâ€¦', 'info');

    try {
      const form = new FormData();
      form.append('file', file);
      const data = await uploadRfp(form);
      addLog(`Pipeline started: ${data.run_id}`, 'success');
      setSelectedRun(data.run_id);

      if (data.status === 'COMPLETED' || data.status === 'SUBMITTED' || data.status === 'REJECTED' || data.status === 'AWAITING_HUMAN_VALIDATION') {
        await openRun(data.run_id);
        setRunning(false);
        loadRuns();
        if (data.status === 'AWAITING_HUMAN_VALIDATION') {
          router.push(`/review?run_id=${data.run_id}`);
        }
      } else {
        connectLiveUpdates(data.run_id);
      }
    } catch (e) {
      addLog(`Error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error');
      setRunning(false);
    }
  }, [file, addLog, loadRuns, connectLiveUpdates, openRun, resetAgents, router]);

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
            <PipelineTimeline agents={agents} />

            {/* Run Details (Checkpoints & Outputs) */}
            {selectedRun && selectedRunStatus && (
              <div className="flex flex-col border-b border-border">
                <CheckpointsPanel rfpId={selectedRun} onRerun={(id) => { openRun(id); loadRuns(); }} />
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
                  runs.slice(0, 3).map(run => (
                    <div key={run.run_id} onClick={() => openRun(run.run_id)} className={`flex items-center justify-between py-4 border-b border-border cursor-pointer hover:bg-muted/10 transition-colors duration-100 ease-linear ${selectedRun === run.run_id ? 'bg-muted/10' : ''}`}>
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
