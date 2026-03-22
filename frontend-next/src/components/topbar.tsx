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
    <header className="sticky top-0 z-40 flex items-center justify-between h-14 px-8 shrink-0
                        bg-background border-b border-border">
      <h1 className="text-[13px] font-bold uppercase tracking-[0.1em] text-muted-foreground">
        {title}
      </h1>
      <div className="flex items-center gap-4 text-[12px] text-muted-foreground ml-auto">
        <ThemeToggle />
        <div className="flex items-center gap-2.5 border-l border-border pl-5">
          <span
            className={`w-1.5 h-1.5 rounded-none ${
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
