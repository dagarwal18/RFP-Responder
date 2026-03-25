'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowUpRight, Loader2, RefreshCw } from 'lucide-react';

import Topbar from '@/components/topbar';
import {
  PageHeader,
  PageSection,
  PageShell,
  PageStat,
  PageStatGrid,
} from '@/components/page-shell';
import { Button } from '@/components/ui/button';
import { fetchRuns } from '@/lib/api';
import type { Run } from '@/lib/types';

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

function getStatusClasses(status: string) {
  const normalized = String(status || '').toUpperCase();

  if (normalized === 'FAILED') {
    return 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300';
  }

  if (normalized === 'RUNNING') {
    return 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-500/20 dark:bg-orange-500/10 dark:text-orange-300';
  }

  return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300';
}

export default function HistoryPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

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
  const completedRuns = runs.filter((run) => (
    ['COMPLETED', 'SUBMITTED', 'AWAITING_HUMAN_VALIDATION', 'REJECTED', 'INTAKE_COMPLETE'].includes(
      String(run.status || '').toUpperCase()
    )
  )).length;
  const activeRuns = runs.filter((run) => String(run.status || '').toUpperCase() === 'RUNNING').length;
  const failedRuns = runs.filter((run) => String(run.status || '').toUpperCase() === 'FAILED').length;

  return (
    <>
      <Topbar title="Execution History" />
      <PageShell>
        <PageHeader
          eyebrow="Manage"
          title="Execution History"
          description="Browse every past pipeline run in one place, then reopen any execution back in the workspace."
          actions={(
            <Button variant="outline" onClick={() => void loadRuns()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          )}
        />

        <div className="space-y-6 py-6">
          <PageStatGrid className="xl:grid-cols-4">
            <PageStat label="Total Runs" value={totalRuns} detail="All executions recorded for this workspace." />
            <PageStat label="Completed" value={completedRuns} detail="Runs that reached a terminal non-failed state." />
            <PageStat label="Running" value={activeRuns} detail="Executions currently still in progress." />
            <PageStat label="Failed" value={failedRuns} detail="Runs that stopped because of an error." />
          </PageStatGrid>

          <PageSection
            title="Past Executions"
            description="Open any run to inspect checkpoints, outputs, and final review state in the main pipeline workspace."
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
                {runs.map((run) => (
                  <button
                    key={run.run_id}
                    type="button"
                    onClick={() => router.push(`/?run_id=${run.run_id}`)}
                    className="flex w-full items-center justify-between gap-6 px-5 py-4 text-left transition-colors hover:bg-muted/40"
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="truncate text-sm font-medium text-foreground">
                        {run.filename?.replace('.pdf', '') || `Execution ${run.run_id.slice(0, 8)}`}
                      </p>
                      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                        <span>{formatRunTimestamp(run.created_at)}</span>
                        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground/80">
                          {run.run_id}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className={`rounded-lg border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${getStatusClasses(run.status)}`}>
                        {formatRunStatus(run.status)}
                      </span>
                      <ArrowUpRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </PageSection>
        </div>
      </PageShell>
    </>
  );
}
