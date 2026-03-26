import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface PageShellProps {
  children: ReactNode;
  className?: string;
}

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}

interface PageStatGridProps {
  children: ReactNode;
  className?: string;
}

interface PageStatProps {
  label: string;
  value: ReactNode;
  detail?: string;
  className?: string;
}

interface PageSectionProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

export function PageShell({ children, className }: PageShellProps) {
  return <div className={cn('app-page', className)}>{children}</div>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn('app-hero', className)}>
      <div className="space-y-2">
        {eyebrow ? (
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {eyebrow}
          </p>
        ) : null}
        <div className="space-y-1">
          <h1 className="text-sm font-bold tracking-[0.08em] text-foreground uppercase">{title}</h1>
          {description ? (
            <p className="max-w-3xl text-[13px] leading-6 text-muted-foreground">{description}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </div>
  );
}

export function PageStatGrid({ children, className }: PageStatGridProps) {
  return <div className={cn('app-stats-grid', className)}>{children}</div>;
}

export function PageStat({ label, value, detail, className }: PageStatProps) {
  return (
    <div className={cn('app-stat-card', className)}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <div className="space-y-1">
        <div className="text-[28px] font-semibold leading-none tracking-tight text-foreground">
          {value}
        </div>
        {detail ? <p className="text-xs leading-5 text-muted-foreground">{detail}</p> : null}
      </div>
    </div>
  );
}

export function PageSection({
  title,
  description,
  actions,
  children,
  className,
  contentClassName,
}: PageSectionProps) {
  return (
    <section className={cn('app-section-card', className)}>
      <div className="flex flex-col gap-3 border-b border-border/70 px-5 py-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-[0.08em] text-foreground">{title}</h2>
          {description ? (
            <p className="max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      <div className={cn('px-5 py-5', contentClassName)}>{children}</div>
    </section>
  );
}
