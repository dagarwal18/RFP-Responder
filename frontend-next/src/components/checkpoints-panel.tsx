import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { STAGES } from '@/lib/types';
import { fetchCheckpoints, rerunPipeline, clearCheckpoints } from '@/lib/api';
import { Play, Trash2, Check } from 'lucide-react';

export default function CheckpointsPanel({ rfpId, onRerun }: { rfpId: string; onRerun: (rfpId: string) => void }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [rerunAgent, setRerunAgent] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const d = await fetchCheckpoints(rfpId);
      setData(d);
    } catch { setData(null); }
    setLoading(false);
  };

  useEffect(() => { load(); }, [rfpId]);

  if (loading) return <div className="p-6 border-b border-border bg-card text-xs text-muted-foreground">Loading checkpoints...</div>;
  if (!data || !data.checkpoints || data.checkpoints.length === 0) return null;

  const cachedSet = new Set(data.checkpoints.map((c: any) => c.agent));
  
  const handleRerun = async () => {
    if (!rerunAgent) return;
    try {
      const res = await rerunPipeline(rfpId, rerunAgent);
      onRerun(res.rfp_id);
    } catch(e: any) {
      alert("Rerun failed: " + e.message);
    }
  };

  const handleClear = async () => {
    if (!confirm('Delete all cached checkpoints? Next run will execute everything from scratch.')) return;
    try {
      await clearCheckpoints(rfpId);
      load();
    } catch(e: any) {
      alert("Clear failed: " + e.message);
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
        {STAGES.map(s => {
          const agentKey = s.key.toLowerCase();
          const isCached = cachedSet.has(agentKey);
          return (
             <span key={s.key} className={`px-2.5 py-1 flex items-center gap-1.5 text-[10px] font-semibold rounded-full border transition-colors ${isCached ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-secondary text-muted-foreground opacity-60'}`}>
                {isCached ? <Check className="w-3 h-3" /> : <div className="w-1.5 h-1.5 rounded-full border border-current" />}
                {s.label}
             </span>
          );
        })}
      </div>
      <div className="flex items-center gap-3">
        <select value={rerunAgent} onChange={e => setRerunAgent(e.target.value)} className="flex-1 h-8 max-w-sm text-xs bg-secondary border border-border rounded-md px-2 outline-none">
          <option value="" disabled>Select agent to re-run from...</option>
          {data.checkpoints.map((cp: any) => {
             const keyLower = cp.agent.toLowerCase();
             const idx = STAGES.findIndex(s => s.key.toLowerCase() === keyLower);
             if (idx < 0 || idx >= STAGES.length - 1) return null;
             const nextAgent = STAGES[idx + 1];
             // Skip displaying rerun for H1 since human step handles itself usually, but we allow it if the API allows it
             return (
               <option key={nextAgent.key} value={nextAgent.key.toLowerCase()}>
                 Keep {STAGES[idx].label} → Re-run {nextAgent.label}
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
