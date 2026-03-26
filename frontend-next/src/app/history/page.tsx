'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowUpRight,
  Download,
  Eye,
  FileText,
  Loader2,
  RefreshCw,
  RotateCcw,
} from 'lucide-react';

import Topbar from '@/components/topbar';
import {
  PageHeader,
  PageSection,
  PageShell,
  PageStat,
  PageStatGrid,
} from '@/components/page-shell';
import { Button } from '@/components/ui/button';
import { fetchRuns, getDownloadUrl } from '@/lib/api';
import type { Run } from '@/lib/types';
import DocumentPreviewModal from '@/components/document-preview-modal';

/* ── Helpers ───────────────────────────────────────────── */

function formatRunTimestamp(value?: string) {
  if (!value) return 'Timestamp unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Timestamp unavailable';
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatRunStatus(value: string) {
  if (value === 'INTAKE_COMPLETE' || value === 'SUBMITTED') return 'COMPLETED';
  return value.replaceAll('_', ' ');
}

const COMPLETED_STATUSES = [
  'COMPLETED',
  'SUBMITTED',
  'INTAKE_COMPLETE',
  'AWAITING_HUMAN_VALIDATION',
];

function isCompleted(status: string) {
  return COMPLETED_STATUSES.includes(String(status || '').toUpperCase());
}

function getStatusClasses(status: string) {
  const normalized = String(status || '').toUpperCase();

  if (normalized === 'FAILED') {
    return 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300';
  }
  if (normalized === 'RUNNING') {
    return 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-500/20 dark:bg-orange-500/10 dark:text-orange-300';
  }
  if (normalized === 'INTERRUPTED') {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300';
  }
  return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300';
}

/* ── Page ──────────────────────────────────────────────── */

export default function HistoryPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  /* Preview modal state */
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewFilename, setPreviewFilename] = useState('');
  const [previewDownloadUrls, setPreviewDownloadUrls] = useState<
    Partial<Record<'pdf' | 'docx' | 'md', string>>
  >({});

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchRuns();
      const sortedRuns = [...(data.runs || [])].sort((left, right) => {
        const leftTime = new Date(left.created_at || 0).getTime();
        const rightTime = new Date(right.created_at || 0).getTime();
        return rightTime - leftTime;
      });
      setRuns(sortedRuns);
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const totalRuns = runs.length;
  const completedRuns = runs.filter((run) =>
    ['COMPLETED', 'SUBMITTED', 'AWAITING_HUMAN_VALIDATION', 'REJECTED', 'INTAKE_COMPLETE'].includes(
      String(run.status || '').toUpperCase(),
    ),
  ).length;
  const activeRuns = runs.filter(
    (run) => String(run.status || '').toUpperCase() === 'RUNNING',
  ).length;
  const failedRuns = runs.filter(
    (run) => String(run.status || '').toUpperCase() === 'FAILED',
  ).length;

  const handlePreview = (run: Run) => {
    setPreviewUrl(getDownloadUrl(run.run_id, { format: 'pdf', inline: true }));
    setPreviewFilename(
      run.filename?.replace('.pdf', '') || `Execution ${run.run_id.slice(0, 8)}`,
    );
    setPreviewDownloadUrls({
      pdf: run.available_formats?.includes('pdf')
        ? getDownloadUrl(run.run_id, { format: 'pdf' })
        : undefined,
      docx: run.available_formats?.includes('docx')
        ? getDownloadUrl(run.run_id, { format: 'docx' })
        : undefined,
      md: run.available_formats?.includes('md')
        ? getDownloadUrl(run.run_id, { format: 'md' })
        : undefined,
    });
    setPreviewOpen(true);
  };

  const handleDownload = (run: Run, format: 'pdf' | 'docx' | 'md') => {
    const link = document.createElement('a');
    link.href = getDownloadUrl(run.run_id, { format });
    link.download = '';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <>
      <Topbar title="Execution History" />
      <PageShell>
        <PageHeader
          eyebrow="Manage"
          title="My Responses"
          description="Browse past pipeline runs, preview generated documents, download responses, or rerun from any checkpoint."
          actions={
            <Button variant="outline" onClick={() => void loadRuns()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          }
        />

        <div className="space-y-6 py-6">
          <PageStatGrid className="xl:grid-cols-4">
            <PageStat
              label="Total Runs"
              value={totalRuns}
              detail="All executions recorded for this workspace."
            />
            <PageStat
              label="Completed"
              value={completedRuns}
              detail="Runs that reached a terminal non-failed state."
            />
            <PageStat
              label="Running"
              value={activeRuns}
              detail="Executions currently still in progress."
            />
            <PageStat
              label="Failed"
              value={failedRuns}
              detail="Runs that stopped because of an error."
            />
          </PageStatGrid>

          <PageSection
            title="Past Executions"
            description="Inspect any run, preview or download the generated response, or resume processing from a checkpoint."
            contentClassName="p-0"
          >
            {loading ? (
              <div className="flex items-center gap-3 px-5 py-10 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading execution history...
              </div>
            ) : runs.length === 0 ? (
              <div className="px-5 py-10 text-sm text-muted-foreground">
                No past executions are available yet.
              </div>
            ) : (
              <div className="divide-y divide-border/70">
                {runs.map((run) => {
                  const completed = isCompleted(run.status);
                  const formats = run.available_formats || [];
                  return (
                    <div
                      key={run.run_id}
                      className="flex w-full items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-muted/40"
                    >
                      {/* Left: info — click to open in workspace */}
                      <button
                        type="button"
                        onClick={() =>
                          router.push(`/?run_id=${run.run_id}`)
                        }
                        className="min-w-0 flex-1 text-left space-y-1"
                      >
                        <p className="truncate text-sm font-medium text-foreground">
                          {run.filename?.replace('.pdf', '') ||
                            `Execution ${run.run_id.slice(0, 8)}`}
                        </p>
                        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                          <span>{formatRunTimestamp(run.created_at)}</span>
                          <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground/80">
                            {run.run_id}
                          </span>
                        </div>
                      </button>

                      {/* Right: actions + badge */}
                      <div className="flex items-center gap-2 shrink-0">
                        {completed && (
                          <>
                            {formats.includes('pdf') && (
                              <>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  title="Preview PDF"
                                  onClick={() => handlePreview(run)}
                                >
                                  <Eye className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  title="Download PDF"
                                  onClick={() => handleDownload(run, 'pdf')}
                                >
                                  <Download className="h-4 w-4" />
                                  PDF
                                </Button>
                              </>
                            )}
                            {formats.includes('docx') && (
                              <Button
                                variant="ghost"
                                size="sm"
                                title="Download DOCX"
                                onClick={() => handleDownload(run, 'docx')}
                              >
                                <FileText className="h-4 w-4" />
                                DOCX
                              </Button>
                            )}
                            {!formats.includes('pdf') && !formats.includes('docx') && formats.includes('md') && (
                              <Button
                                variant="ghost"
                                size="sm"
                                title="Download Markdown"
                                onClick={() => handleDownload(run, 'md')}
                              >
                                <Download className="h-4 w-4" />
                                MD
                              </Button>
                            )}
                          </>
                        )}

                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Open in workspace"
                          onClick={() =>
                            router.push(`/?run_id=${run.run_id}`)
                          }
                        >
                          {completed ? (
                            <RotateCcw className="h-4 w-4" />
                          ) : (
                            <ArrowUpRight className="h-4 w-4" />
                          )}
                        </Button>

                        <span
                          className={`rounded-lg border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${getStatusClasses(run.status)}`}
                        >
                          {formatRunStatus(run.status)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </PageSection>
        </div>
      </PageShell>

      {/* Preview Modal */}
      <DocumentPreviewModal
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        previewUrl={previewUrl}
        filename={previewFilename}
        downloadUrls={previewDownloadUrls}
      />
    </>
  );
}
