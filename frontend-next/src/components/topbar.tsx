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
    <header className="sticky top-0 z-40 flex items-center justify-between h-14 px-6 
                        bg-background/90 backdrop-blur-xl border-b border-border">
      <h1 className="text-base font-semibold text-foreground tracking-tight">
        {title}
      </h1>
      <div className="flex items-center gap-3 text-xs text-muted-foreground border-l pl-4 border-border ml-auto">
        <ThemeToggle />
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${
              status === 'online'
                ? 'bg-success shadow-[0_0_6px_var(--color-success)]'
                : status === 'offline'
                ? 'bg-error shadow-[0_0_6px_var(--color-error)]'
                : 'bg-warning animate-pulse'
            }`}
          />
          {status === 'online' ? 'Connected' : status === 'offline' ? 'API Offline' : 'Connecting…'}
        </div>
      </div>
    </header>
  );
}
