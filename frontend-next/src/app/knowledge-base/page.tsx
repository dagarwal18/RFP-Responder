'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Topbar from '@/components/topbar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { apiFetch, formatSize, formatTime } from '@/lib/api';
import type { KBStats, KBFile, LogEntry } from '@/lib/types';
import {
  RefreshCw, Trash2, Search, Sprout,
  Upload, Loader2
} from 'lucide-react';

export default function KnowledgeBasePage() {
  const [stats, setStats] = useState<KBStats>({ vectors: 0, namespaces: 0, configs: 0 });
  const [files, setFiles] = useState<KBFile[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [queryInput, setQueryInput] = useState('');
  const [queryType, setQueryType] = useState('');
  const [queryResults, setQueryResults] = useState<Array<{ score: number; text: string }>>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addLog = useCallback((msg: string, type: LogEntry['type'] = 'default') => {
    setLogs(prev => [...prev, { time: formatTime(), message: msg, type }]);
  }, []);

  const loadStats = useCallback(async () => {
    try { setStats(await apiFetch<KBStats>('/kb/stats')); } catch {}
  }, []);

  const loadFiles = useCallback(async () => {
    try { const d = await apiFetch<{ files: KBFile[] }>('/kb/files'); setFiles(d.files || []); } catch {}
  }, []);

  useEffect(() => { loadStats(); loadFiles(); }, [loadStats, loadFiles]);

  const uploadFile = useCallback(async () => {
    if (!selectedFile) return;
    setUploading(true);
    addLog(`Uploading ${selectedFile.name}…`, 'info');
    try {
      const form = new FormData();
      form.append('file', selectedFile);
      await apiFetch('/kb/upload', { method: 'POST', headers: {}, body: form });
      addLog(`Uploaded ${selectedFile.name}`, 'success');
      setSelectedFile(null);
      loadStats(); loadFiles();
    } catch (e) { addLog(`Error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error'); }
    finally { setUploading(false); }
  }, [selectedFile, addLog, loadStats, loadFiles]);

  const runQuery = useCallback(async () => {
    if (!queryInput.trim()) return;
    addLog(`Querying: "${queryInput}"`, 'info');
    try {
      const params = new URLSearchParams({ q: queryInput });
      if (queryType) params.set('type', queryType);
      const d = await apiFetch<{ results: Array<{ score: number; text: string }> }>(`/kb/query?${params}`);
      setQueryResults(d.results || []);
      addLog(`Found ${(d.results || []).length} results`, 'success');
    } catch (e) { addLog(`Error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error'); }
  }, [queryInput, queryType, addLog]);

  const typeColor = (t: string) => {
    const map: Record<string, string> = {
      capability: 'bg-primary/15 text-primary border-primary/30',
      past_proposal: 'bg-warning/15 text-warning border-warning/30',
      certification: 'bg-success/15 text-success border-success/30',
      pricing: 'bg-info/15 text-info border-info/30',
      legal: 'bg-error/15 text-error border-error/30',
    };
    return map[t] || '';
  };

  return (
    <div className="flex flex-1 h-full overflow-hidden bg-background">
      {/* MAIN WORKSPACE ZONE */}
      <div className="flex-1 flex flex-col min-w-0 border-r border-border relative">
        <Topbar title="Knowledge Base" />
        <ScrollArea className="flex-1">
          <div className="flex flex-col">
            
            {/* Stats Strip */}
            <div className="flex items-center border-b border-border divide-x divide-border">
              {[
                { label: 'Vectors', value: stats.vectors },
                { label: 'Namespaces', value: stats.namespaces },
                { label: 'Configs', value: stats.configs },
              ].map(s => (
                <div key={s.label} className="flex-1 px-8 py-5 flex items-center justify-between">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{s.label}</span>
                  <span className="text-2xl font-bold text-foreground">{s.value}</span>
                </div>
              ))}
            </div>

            {/* Upload Strip */}
            <div 
              className="px-8 py-6 border-b border-border flex items-center justify-between group cursor-pointer hover:bg-muted/10 transition-colors duration-100 ease-linear" 
              onClick={() => fileInputRef.current?.click()}
            >
              <input ref={fileInputRef} type="file" accept=".pdf" className="hidden" onChange={e => { if (e.target.files) setSelectedFile(e.target.files[0]) }} />
              <div className="flex flex-col">
                <span className="text-[14px] font-medium text-foreground tracking-tight">Upload Document</span>
                <span className="text-[13px] text-muted-foreground mt-1.5">Select a PDF to extract and ingest into the vector database.</span>
                {selectedFile && (
                  <div className="flex items-center gap-3 mt-4 text-[13px] text-muted-foreground border-l-2 border-primary pl-3 bg-secondary/50 py-2">
                    <span className="font-medium text-foreground">{selectedFile.name}</span>
                    <span>{formatSize(selectedFile.size)}</span>
                  </div>
                )}
              </div>
              <Button 
                onClick={(e) => { e.stopPropagation(); uploadFile(); }}
                disabled={!selectedFile || uploading}
                className="bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-6 text-[13px] font-medium shrink-0 ml-6 cursor-pointer"
              >
                {uploading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Upload className="w-4 h-4 mr-2" />}
                {uploading ? 'Processing' : 'Upload to Base'}
              </Button>
            </div>

            {/* Document List */}
            <div className="p-8 border-b border-border">
              <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-3">
                  <h2 className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em]">Indexed Documents</h2>
                  <Badge variant="secondary" className="text-[10px]">{files.length}</Badge>
                </div>
                <div className="flex items-center gap-5">
                  <span 
                    className="text-[12px] text-primary cursor-pointer hover:underline underline-offset-4 flex items-center gap-1.5"
                    onClick={async () => { addLog('Seeding…', 'info'); try { await apiFetch('/kb/seed', { method: 'POST' }); addLog('Done', 'success'); loadStats(); loadFiles(); } catch(e) { addLog(`Error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error'); }}}
                  >
                    <Sprout className="w-3.5 h-3.5" /> Seed JSON
                  </span>
                  <span 
                    className="text-[12px] text-destructive cursor-pointer hover:underline underline-offset-4 flex items-center gap-1.5"
                    onClick={async () => { addLog('Clearing…', 'info'); try { await apiFetch('/kb/clear', { method: 'DELETE' }); addLog('Cleared', 'success'); loadStats(); loadFiles(); } catch(e) { addLog(`${e}`, 'error'); }}}
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Clear Index
                  </span>
                  <div className="w-[1px] h-4 bg-border mx-1" />
                  <RefreshCw className="w-3.5 h-3.5 text-muted-foreground cursor-pointer hover:text-foreground transition-colors" onClick={loadFiles} />
                </div>
              </div>

              <div className="flex flex-col border-t border-border w-full">
                {files.length === 0 ? (
                  <div className="text-[13px] text-muted-foreground py-6">No documents indexed in the vector database.</div>
                ) : (
                  files.map((f, i) => (
                    <div key={i} className="flex items-center justify-between py-4 border-b border-border hover:bg-muted/10 transition-colors duration-100 ease-linear">
                      <span className="text-[13px] font-medium text-foreground truncate flex-1 min-w-0 pr-4">{f.filename}</span>
                      <div className="flex items-center gap-4 shrink-0">
                        <Badge variant="outline" className={`text-[10px] rounded-none ${typeColor(f.doc_type)}`}>{f.doc_type}</Badge>
                        <span className="text-[11px] text-muted-foreground w-[70px] text-right font-mono">{f.chunks} <span className="font-sans">chunks</span></span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Query Tester */}
            <div className="p-8">
              <h2 className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em] mb-6">Semantic Query Tester</h2>
              <div className="flex gap-3">
                <Input value={queryInput} onChange={e => setQueryInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && runQuery()} placeholder="Test similarity search query…" className="flex-1 bg-secondary border-border h-9 shadow-none rounded-none focus-visible:ring-1 text-[13px]" />
                <select value={queryType} onChange={e => setQueryType(e.target.value)} className="px-3 h-9 rounded-none text-[13px] bg-secondary border border-border text-foreground outline-none cursor-pointer">
                  <option value="">All Types</option><option value="capability">Capability</option><option value="past_proposal">Proposal</option><option value="certification">Cert</option><option value="pricing">Pricing</option><option value="legal">Legal</option>
                </select>
                <Button onClick={runQuery} className="h-9 px-6 cursor-pointer shadow-none rounded-none bg-foreground text-background hover:bg-foreground/90 border-none">
                  <Search className="w-3.5 h-3.5 mr-2" /> Query
                </Button>
              </div>
              {queryResults.length > 0 && (
                <div className="mt-6 flex flex-col gap-3">
                  {queryResults.map((r, i) => (
                    <div key={i} className="p-4 bg-secondary/50 border-l-[3px] border-primary text-[13px]">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-foreground text-[11px] uppercase tracking-wider">Relevance Matrix: {(r.score * 100).toFixed(1)}%</span>
                      </div>
                      <p className="text-muted-foreground leading-relaxed">{r.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

          </div>
        </ScrollArea>
      </div>

      {/* RIGHT CONTEXT ZONE */}
      <div className="w-[360px] min-w-[360px] max-w-[360px] shrink-0 bg-sidebar flex flex-col z-10 border-l border-border">
        <div className="h-14 border-b border-border flex items-center px-6 shrink-0 bg-background/50">
          <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em]">Activity Stream</span>
        </div>
        <div className="flex-1 overflow-y-auto p-6 font-mono text-[11px] leading-[1.6] text-muted-foreground space-y-2 break-all whitespace-pre-wrap">
          {logs.length === 0 ? (
            <span className="opacity-40">Awaiting database queries...</span>
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
