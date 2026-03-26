'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { ThemeToggle } from '@/components/theme-toggle';

export default function Topbar({ title }: { title: string }) {
  const [status, setStatus] = useState<'connecting' | 'online' | 'offline'>('connecting');

  useEffect(() => {
    const check = async () => {
      try {
        await apiFetch('/health');
        setStatus('online');
      } catch {
        setStatus('offline');
      }
    };
    check();
    const interval = setInterval(check, 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header
      className="sticky top-0 z-40 flex h-14 shrink-0 items-center justify-between border-b border-border/70 bg-background/92 px-6 sm:px-8 lg:px-10 backdrop-blur-xl"
    >
      <h1 className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {title}
      </h1>
      <div className="ml-auto flex items-center gap-4 text-[12px] text-muted-foreground">
        <ThemeToggle />
        <div className="flex items-center gap-2.5 rounded-full border border-border/70 bg-card/90 px-3 py-1.5 shadow-[0_4px_12px_rgba(15,23,42,0.03)] dark:shadow-none">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              status === 'online'
                ? 'bg-success'
                : status === 'offline'
                ? 'bg-error'
                : 'bg-warning'
            }`}
          />
          <span className="font-medium tracking-wide">
            {status === 'online' ? 'CONNECTED' : status === 'offline' ? 'OFFLINE' : 'CONNECTING...'}
          </span>
        </div>
      </div>
    </header>
  );
}
