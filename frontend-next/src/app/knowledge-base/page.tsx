'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Loader2,
  RefreshCw,
  Search,
  Sprout,
  Trash2,
  Upload,
} from 'lucide-react';

import Topbar from '@/components/topbar';
import {
  PageHeader,
  PageSection,
  PageShell,
  PageStat,
  PageStatGrid,
} from '@/components/page-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  apiFetch,
  fetchKBFiles,
  fetchKBStats,
  formatSize,
  formatTime,
} from '@/lib/api';
import type { KBFile, KBStats, LogEntry } from '@/lib/types';

export default function KnowledgeBasePage() {
  const [stats, setStats] = useState<KBStats>({ vectors: 0, namespaces: 0, configs: 0 });
  const [files, setFiles] = useState<KBFile[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [queryInput, setQueryInput] = useState('');
  const [queryType, setQueryType] = useState('');
  const [queryResults, setQueryResults] = useState<Array<{ score: number; text: string }>>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addLog = useCallback((message: string, type: LogEntry['type'] = 'default') => {
    setLogs((previous) => [...previous, { time: formatTime(), message, type }]);
  }, []);

  const loadStats = useCallback(async () => {
    try {
      setStats(await fetchKBStats());
    } catch {}
  }, []);

  const loadFiles = useCallback(async () => {
    try {
      const data = await fetchKBFiles();
      setFiles(data.files || []);
    } catch {}
  }, []);

  useEffect(() => {
    void loadStats();
    void loadFiles();
  }, [loadFiles, loadStats]);

  const uploadFiles = useCallback(async () => {
    if (selectedFiles.length === 0) return;
    setUploading(true);

    let successCount = 0;
    let failCount = 0;

    try {
      for (const [index, selectedFile] of selectedFiles.entries()) {
        addLog(`Uploading ${selectedFile.name} (${index + 1}/${selectedFiles.length})...`, 'info');
        const form = new FormData();
        form.append('file', selectedFile);
        try {
          await apiFetch('/api/knowledge/upload', {
            method: 'POST',
            headers: {},
            body: form,
          });
          addLog(`Uploaded ${selectedFile.name}`, 'success');
          successCount += 1;
        } catch (error) {
          addLog(
            `Upload failed for ${selectedFile.name}: ${error instanceof Error ? error.message : 'Unknown'}`,
            'error'
          );
          failCount += 1;
        }
      }

      if (selectedFiles.length > 1) {
        addLog(
          `Batch upload complete. ${successCount} succeeded, ${failCount} failed.`,
          failCount > 0 ? 'info' : 'success'
        );
      }

      setSelectedFiles([]);
      void loadStats();
      void loadFiles();
    } catch (error) {
      addLog(`Error: ${error instanceof Error ? error.message : 'Unknown'}`, 'error');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [addLog, loadFiles, loadStats, selectedFiles]);

  const runQuery = useCallback(async () => {
    if (!queryInput.trim()) return;
    addLog(`Querying: "${queryInput}"`, 'info');
    try {
      const body = JSON.stringify({
        query: queryInput,
        top_k: 5,
        doc_type: queryType || '',
      });
      const data = await apiFetch<{ results: Array<{ score: number; text: string }> }>(
        '/api/knowledge/query',
        { method: 'POST', body }
      );
      setQueryResults(data.results || []);
      addLog(`Found ${(data.results || []).length} results`, 'success');
    } catch (error) {
      addLog(`Error: ${error instanceof Error ? error.message : 'Unknown'}`, 'error');
    }
  }, [addLog, queryInput, queryType]);

  const seedJson = async () => {
    addLog('Seeding JSON knowledge sources...', 'info');
    try {
      await apiFetch('/api/knowledge/seed', { method: 'POST' });
      addLog('Knowledge base seeded successfully.', 'success');
      void loadStats();
      void loadFiles();
    } catch (error) {
      addLog(`Error: ${error instanceof Error ? error.message : 'Unknown'}`, 'error');
    }
  };

  const clearIndex = async () => {
    addLog('Clearing vector index...', 'info');
    try {
      await apiFetch('/api/knowledge/index', { method: 'DELETE' });
      addLog('Index cleared.', 'success');
      void loadStats();
      void loadFiles();
    } catch (error) {
      addLog(`${error instanceof Error ? error.message : String(error)}`, 'error');
    }
  };

  const docTypeClass = (type: string) =>
    ({
      capability:
        'border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-400/25 dark:bg-orange-500/12 dark:text-orange-300',
      past_proposal:
        'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-400/25 dark:bg-sky-500/12 dark:text-sky-300',
      certification:
        'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-500/12 dark:text-emerald-300',
      pricing:
        'border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-400/25 dark:bg-violet-500/12 dark:text-violet-300',
      legal:
        'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-400/25 dark:bg-rose-500/12 dark:text-rose-300',
    }[type] || '');

  const totalSelectedSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);

  return (
    <>
      <Topbar title="Knowledge Base" />
      <PageShell>
        <PageHeader
          eyebrow="Manage"
          title="Knowledge Base"
          description="Upload reference material, inspect indexed content, and test semantic retrieval against the current vector store."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={seedJson}>
                <Sprout className="mr-2 h-4 w-4" />
                Seed JSON
              </Button>
              <Button variant="outline" onClick={clearIndex}>
                <Trash2 className="mr-2 h-4 w-4" />
                Clear Index
              </Button>
              <Button variant="outline" onClick={() => void loadFiles()}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh
              </Button>
            </div>
          }
        />

        <div className="space-y-6 py-6">
          <PageStatGrid className="xl:grid-cols-3">
            <PageStat label="Vectors" value={stats.vectors} detail="Indexed chunks available for retrieval." />
            <PageStat
              label="Namespaces"
              value={stats.namespaces}
              detail="Organized stores backing the active corpus."
            />
            <PageStat
              label="Configs"
              value={stats.configs}
              detail="Knowledge sources and ingestion settings currently configured."
            />
          </PageStatGrid>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-6">
              <PageSection
                title="Upload Documents"
                description="Add one or more PDFs to the vector database. The app will parse, chunk, and index them for retrieval."
                actions={
                  <Button onClick={() => fileInputRef.current?.click()} variant="outline">
                    <Upload className="mr-2 h-4 w-4" />
                    Choose Files
                  </Button>
                }
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  multiple
                  className="hidden"
                  onChange={(event) => {
                    if (event.target.files) setSelectedFiles(Array.from(event.target.files));
                  }}
                />

                <div className="space-y-4">
                  <div className="rounded-2xl border border-dashed border-border/70 bg-secondary/25 px-4 py-5">
                    {selectedFiles.length === 0 ? (
                      <div className="space-y-1 text-sm text-muted-foreground">
                        <p className="font-medium text-foreground">No files selected yet.</p>
                        <p>Choose PDFs to stage them for upload.</p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <p className="text-sm font-medium text-foreground">
                          {selectedFiles.length === 1
                            ? selectedFiles[0].name
                            : `${selectedFiles.length} files selected`}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          Total size: {formatSize(totalSelectedSize)}
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <Button onClick={uploadFiles} disabled={selectedFiles.length === 0 || uploading}>
                      {uploading ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Upload className="mr-2 h-4 w-4" />
                      )}
                      {uploading ? 'Processing...' : 'Upload to Base'}
                    </Button>
                    <p className="text-sm text-muted-foreground">
                      Multi-file upload is supported and progress will appear in the activity stream.
                    </p>
                  </div>
                </div>
              </PageSection>

              <PageSection
                title="Indexed Documents"
                description="Review the currently indexed files and the type assigned to each source."
                actions={<Badge variant="secondary">{files.length} files</Badge>}
                contentClassName="p-0"
              >
                {files.length === 0 ? (
                  <div className="px-5 py-14 text-center">
                    <p className="text-sm font-medium text-foreground">No indexed documents yet.</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Upload a PDF or seed the JSON sources to populate the knowledge base.
                    </p>
                  </div>
                ) : (
                  <div className="divide-y divide-border/60">
                    {files.map((file) => (
                      <div
                        key={`${file.filename}-${file.doc_type}`}
                        className="flex flex-col gap-3 px-5 py-4 md:flex-row md:items-center md:justify-between"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-foreground">{file.filename}</p>
                          <p className="mt-1 text-sm text-muted-foreground">
                            {file.chunks} chunks indexed
                          </p>
                        </div>
                        <Badge variant="outline" className={docTypeClass(file.doc_type)}>
                          {file.doc_type}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </PageSection>

              <PageSection
                title="Semantic Query Tester"
                description="Run an ad hoc retrieval query against the current vector store to inspect matching chunks."
              >
                <div className="space-y-4">
                  <div className="flex flex-col gap-3 lg:flex-row">
                    <Input
                      value={queryInput}
                      onChange={(event) => setQueryInput(event.target.value)}
                      onKeyDown={(event) => event.key === 'Enter' && void runQuery()}
                      placeholder="Test a similarity search query..."
                      className="h-11 flex-1 bg-secondary/40"
                    />
                    <select
                      value={queryType}
                      onChange={(event) => setQueryType(event.target.value)}
                      className="h-11 rounded-xl border border-border bg-secondary/40 px-3 text-sm text-foreground outline-none"
                    >
                      <option value="">All Types</option>
                      <option value="capability">Capability</option>
                      <option value="past_proposal">Proposal</option>
                      <option value="certification">Certification</option>
                      <option value="pricing">Pricing</option>
                      <option value="legal">Legal</option>
                    </select>
                    <Button onClick={runQuery}>
                      <Search className="mr-2 h-4 w-4" />
                      Query
                    </Button>
                  </div>

                  {queryResults.length > 0 ? (
                    <div className="space-y-3">
                      {queryResults.map((result, index) => (
                        <div
                          key={`${result.score}-${index}`}
                          className="rounded-2xl border border-border/70 bg-secondary/25 px-4 py-4"
                        >
                          <div className="mb-2 flex items-center justify-between gap-3">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                              Match {index + 1}
                            </p>
                            <Badge variant="outline">
                              {(result.score * 100).toFixed(1)}% relevance
                            </Badge>
                          </div>
                          <p className="text-sm leading-6 text-foreground/90">{result.text}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-secondary/20 px-4 py-8 text-center text-sm text-muted-foreground">
                      Run a query to inspect the top retrieved chunks here.
                    </div>
                  )}
                </div>
              </PageSection>
            </div>

            <aside className="app-side-panel h-fit overflow-hidden">
              <div className="border-b border-border/70 px-5 py-4">
                <p className="text-base font-semibold text-foreground">Activity Stream</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Uploads, indexing, queries, and maintenance actions appear here.
                </p>
              </div>
              <ScrollArea className="h-[540px]">
                <div className="space-y-3 px-5 py-5 font-mono text-[12px] leading-6">
                  {logs.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Awaiting activity...</p>
                  ) : (
                    logs.map((entry, index) => (
                      <div key={`${entry.time}-${index}`} className="flex gap-3">
                        <span className="shrink-0 text-muted-foreground/70">[{entry.time}]</span>
                        <span
                          className={
                            entry.type === 'success'
                              ? 'text-emerald-600 dark:text-emerald-300'
                              : entry.type === 'error'
                                ? 'text-rose-600 dark:text-rose-300'
                                : entry.type === 'info'
                                  ? 'text-foreground'
                                  : 'text-muted-foreground'
                          }
                        >
                          {entry.message}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </ScrollArea>
            </aside>
          </div>
        </div>
      </PageShell>
    </>
  );
}
