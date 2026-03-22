'use client';

import { useEffect, useRef } from 'react';
import type { LogEntry } from '@/lib/types';

interface LogViewerProps {
  logs: LogEntry[];
  maxHeight?: string;
}

const typeColors: Record<string, string> = {
  success: 'text-success',
  error: 'text-error',
  info: 'text-info',
  default: 'text-text-secondary',
};

export default function LogViewer({ logs, maxHeight = '180px' }: LogViewerProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [logs]);

  return (
    <div
      ref={ref}
      className="bg-bg-secondary border border-border rounded-lg p-3 overflow-y-auto font-mono text-xs leading-relaxed"
      style={{ maxHeight }}
    >
      {logs.length === 0 ? (
        <span className="text-text-muted italic">No activity yet…</span>
      ) : (
        logs.map((entry, i) => (
          <div key={i} className="flex gap-2">
            <span className="text-text-muted shrink-0">{entry.time}</span>
            <span className={typeColors[entry.type] || typeColors.default}>{entry.message}</span>
          </div>
        ))
      )}
    </div>
  );
}
