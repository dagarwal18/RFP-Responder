import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  CHECKPOINT_AGENT_ORDER,
  CHECKPOINT_LABELS,
  clearCheckpoints,
  fetchCheckpoints,
  rerunPipeline,
} from '@/lib/api';
import { Check, Play, Trash2 } from 'lucide-react';

export default function CheckpointsPanel({ rfpId, onRerun }: { rfpId: string; onRerun: (rfpId: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [rerunAgent, setRerunAgent] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const nextData = await fetchCheckpoints(rfpId);
      setData(nextData);
    } catch {
      setData(null);
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, [rfpId]);

  if (loading) {
    return <div className="p-6 border-b border-border bg-card text-xs text-muted-foreground">Loading checkpoints...</div>;
  }

  if (!data || !data.checkpoints || data.checkpoints.length === 0) {
    return null;
  }

  const cachedSet = new Set((data.checkpoints || []).map((checkpoint: any) => checkpoint.agent));
  const rerunnableAgents = Array.isArray(data.rerunnable_from) ? data.rerunnable_from : [];

  const handleRerun = async () => {
    if (!rerunAgent) return;
    try {
      const response = await rerunPipeline(rfpId, rerunAgent);
      onRerun(response.rfp_id || rfpId);
    } catch (error: any) {
      alert(`Rerun failed: ${error.message}`);
    }
  };

  const handleClear = async () => {
    if (!confirm('Delete all cached checkpoints? Next run will execute everything from scratch.')) return;
    try {
      await clearCheckpoints(rfpId);
      setRerunAgent('');
      load();
    } catch (error: any) {
      alert(`Clear failed: ${error.message}`);
    }
  };

  return (
    <div className="p-6 border-b border-border bg-card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-[0.1em]">Checkpoints / Cache</h3>
        <Button variant="ghost" size="sm" onClick={handleClear} className="h-7 text-[11px] text-error hover:text-error/90 hover:bg-error/10">
          <Trash2 className="w-3 h-3 mr-1.5" /> Clear Cache
        </Button>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {CHECKPOINT_AGENT_ORDER.map((agentKey) => {
          const isCached = cachedSet.has(agentKey);
          return (
            <span key={agentKey} className={`px-2.5 py-1 flex items-center gap-1.5 text-[10px] font-semibold rounded-full border transition-colors ${isCached ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-secondary text-muted-foreground opacity-60'}`}>
              {isCached ? <Check className="w-3 h-3" /> : <div className="w-1.5 h-1.5 rounded-full border border-current" />}
              {CHECKPOINT_LABELS[agentKey] || agentKey}
            </span>
          );
        })}
      </div>

      <div className="flex items-center gap-3">
        <select value={rerunAgent} onChange={(e) => setRerunAgent(e.target.value)} className="flex-1 h-8 max-w-sm text-xs bg-secondary border border-border rounded-md px-2 outline-none">
          <option value="" disabled>Select agent to re-run from...</option>
          {rerunnableAgents.map((agent: string) => {
            if (agent === 'a1_intake') return null;
            const index = CHECKPOINT_AGENT_ORDER.indexOf(agent as (typeof CHECKPOINT_AGENT_ORDER)[number]);
            if (index <= 0) return null;
            const previousAgent = CHECKPOINT_AGENT_ORDER[index - 1];
            return (
              <option key={agent} value={agent}>
                Keep {CHECKPOINT_LABELS[previousAgent] || previousAgent} - Re-run {CHECKPOINT_LABELS[agent] || agent}
              </option>
            );
          })}
        </select>
        <Button size="sm" disabled={!rerunAgent} onClick={handleRerun} className="h-8 text-[11px] cursor-pointer">
          <Play className="w-3 h-3 mr-1.5" /> Re-execute Pipeline
        </Button>
      </div>
    </div>
  );
}
