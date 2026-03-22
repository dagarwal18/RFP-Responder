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
  Library, RefreshCw, Trash2, Search, FolderOpen, Sprout,
  Upload, FileText
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
    <>
      <Topbar title="Knowledge Base" />
      <ScrollArea className="flex-1">
        <div className="p-8 space-y-8 max-w-6xl mx-auto w-full">
          {/* Stats */}
          <div className="grid grid-cols-3 gap-8">
            {[
              { label: 'Vectors', value: stats.vectors },
              { label: 'Namespaces', value: stats.namespaces },
              { label: 'Configs', value: stats.configs },
            ].map(s => (
              <Card key={s.label} className="bg-card border-border">
                <CardContent className="text-center py-5">
                  <p className="text-3xl font-bold text-foreground">{s.value}</p>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mt-1">{s.label}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Upload + Documents */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Library className="w-4 h-4 text-primary" strokeWidth={1.75} />
                  Upload Documents
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  className="flex flex-col items-center justify-center gap-3 p-8 rounded-lg
                             border-2 border-dashed border-border hover:border-muted-foreground/30
                             transition-colors cursor-pointer group"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input ref={fileInputRef} type="file" accept=".pdf" multiple className="hidden" onChange={e => e.target.files?.[0] && setSelectedFile(e.target.files[0])} />
                  <Upload className="w-6 h-6 text-muted-foreground group-hover:text-foreground transition-colors" strokeWidth={1.5} />
                  <p className="text-sm text-muted-foreground">Drop company docs or <span className="text-primary">click to browse</span></p>
                </div>
                {selectedFile && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground bg-secondary rounded-md px-3 py-2">
                    <FileText className="w-3.5 h-3.5" />
                    <span className="font-medium text-foreground">{selectedFile.name}</span>
                    <span>({formatSize(selectedFile.size)})</span>
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button onClick={uploadFile} disabled={!selectedFile || uploading} className="cursor-pointer">Upload to KB</Button>
                  <Button variant="outline" size="sm" onClick={async () => { addLog('Seeding…', 'info'); try { await apiFetch('/kb/seed', { method: 'POST' }); addLog('Done', 'success'); loadStats(); loadFiles(); } catch(e) { addLog(`Error: ${e instanceof Error ? e.message : 'Unknown'}`, 'error'); }}} className="cursor-pointer">
                    <Sprout className="w-3.5 h-3.5 mr-1.5" /> Seed from JSON
                  </Button>
                  <Button variant="outline" size="sm" className="text-destructive border-destructive/40 hover:bg-destructive/10 cursor-pointer"
                    onClick={async () => { addLog('Clearing…', 'info'); try { await apiFetch('/kb/clear', { method: 'DELETE' }); addLog('Cleared', 'success'); loadStats(); loadFiles(); } catch(e) { addLog(`${e}`, 'error'); }}}>
                    <Trash2 className="w-3.5 h-3.5 mr-1.5" /> Clear
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-card border-border">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between w-full">
                  <CardTitle className="text-base font-semibold flex items-center gap-2">
                    <FolderOpen className="w-4 h-4 text-primary" strokeWidth={1.75} />
                    Documents
                  </CardTitle>
                  <Button variant="ghost" size="icon" onClick={loadFiles} className="h-8 w-8 cursor-pointer">
                    <RefreshCw className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {files.length === 0 ? (
                  <div className="text-center py-10 text-muted-foreground text-sm px-6">No uploads yet.</div>
                ) : (
                  <ScrollArea className="max-h-64">
                    <div className="divide-y divide-border">
                      {files.map((f, i) => (
                        <div key={i} className="flex items-center justify-between px-6 py-2.5 hover:bg-secondary/50 transition-colors">
                          <span className="text-sm font-medium text-foreground truncate flex-1 min-w-0">{f.filename}</span>
                          <div className="flex items-center gap-2 ml-3 shrink-0">
                            <Badge variant="outline" className={`text-[10px] ${typeColor(f.doc_type)}`}>{f.doc_type}</Badge>
                            <span className="text-[11px] text-muted-foreground">{f.chunks} chunks</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Query */}
          <Card className="bg-card border-border">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Search className="w-4 h-4 text-primary" strokeWidth={1.75} />
                Query Tester
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input value={queryInput} onChange={e => setQueryInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && runQuery()} placeholder="Test query…" className="bg-secondary border-border" />
                <select value={queryType} onChange={e => setQueryType(e.target.value)} className="px-3 py-2 rounded-md text-xs bg-secondary border border-border text-foreground">
                  <option value="">All</option><option value="capability">Capability</option><option value="past_proposal">Proposal</option><option value="certification">Cert</option><option value="pricing">Pricing</option><option value="legal">Legal</option>
                </select>
                <Button variant="outline" size="sm" onClick={runQuery} className="cursor-pointer"><Search className="w-3.5 h-3.5 mr-1.5" /> Query</Button>
              </div>
              {queryResults.length > 0 && (
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {queryResults.map((r, i) => (
                    <div key={i} className="p-3 bg-secondary border border-border rounded-lg text-xs">
                      <span className="font-semibold text-primary">{(r.score * 100).toFixed(1)}%</span>
                      <p className="mt-1 text-muted-foreground">{r.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Logs */}
          <Card className="bg-card border-border">
            <CardHeader className="pb-3"><CardTitle className="text-base font-semibold">Activity Log</CardTitle></CardHeader>
            <CardContent className="p-0">
              <div className="bg-background/50 rounded-b-lg mx-3 mb-3 border border-border overflow-hidden">
                <ScrollArea className="h-[160px]">
                  <div className="p-3 font-mono text-xs leading-relaxed space-y-0.5">
                    {logs.length === 0 ? <span className="text-muted-foreground italic">No activity yet…</span> :
                      logs.map((e, i) => (
                        <div key={i} className="flex gap-2">
                          <span className="text-muted-foreground shrink-0">[{e.time}]</span>
                          <span className={e.type === 'success' ? 'text-success' : e.type === 'error' ? 'text-error' : e.type === 'info' ? 'text-info' : 'text-muted-foreground'}>{e.message}</span>
                        </div>
                      ))}
                  </div>
                </ScrollArea>
              </div>
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
    </>
  );
}
