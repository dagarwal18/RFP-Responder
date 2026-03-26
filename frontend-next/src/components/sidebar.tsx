'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  GitBranch,
  FileSearch,
  Library,
  ScrollText,
  Building2,
  History,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';

const BrandLogo = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
    {/* Rigid back folder tab */}
    <path d="M2 4h7l2 2h11v14H2V4z" fill="currentColor" fillOpacity="0.8" />
    {/* Document cutout page */}
    <path d="M5 7h14v10H5V7z" fill="hsl(var(--background))" />
    {/* Subtle rigid text lines inside document */}
    <path d="M7 9h10v1H7V9z" fill="currentColor" fillOpacity="0.4" />
    <path d="M7 11.5h10v1H7v-1z" fill="currentColor" fillOpacity="0.4" />
    <path d="M7 14h6v1H7v-1z" fill="currentColor" fillOpacity="0.4" />
    {/* Monochromatic angled front folder flap */}
    <path d="M1 10h22l-2 10H3L1 10z" fill="currentColor" />
    {/* 1px separator line for depth projection */}
    <path d="M2.5 10.5h19" stroke="hsl(var(--background))" strokeWidth="1" strokeOpacity="0.5" />
  </svg>
);

const navItems = [
  {
    group: 'WORKSPACE',
    items: [
      { href: '/', label: 'Pipeline', icon: GitBranch },
      { href: '/review', label: 'Review', icon: FileSearch },
    ],
  },
  {
    group: 'MANAGE',
    items: [
      { href: '/history', label: 'History', icon: History },
      { href: '/knowledge-base', label: 'Knowledge Base', icon: Library },
      { href: '/policies', label: 'Policies', icon: ScrollText },
      { href: '/company-profile', label: 'Company Profile', icon: Building2 },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (localStorage.getItem('sidebar-collapsed') === 'true') {
      setCollapsed(true);
    }
  }, []);

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      localStorage.setItem('sidebar-collapsed', String(!prev));
      return !prev;
    });
  }, []);

  return (
    <aside
      className={`
        sticky top-0 h-screen shrink-0 border-r border-sidebar-border/80 bg-sidebar/92
        transition-all duration-150 ease-linear z-50
        ${collapsed ? 'w-[76px]' : 'w-[256px]'}
      `}
    >
      <div className="flex h-full flex-col">
        <div className="flex h-14 shrink-0 items-center gap-3 border-b border-sidebar-border/80 px-6">
          <BrandLogo className="h-[22px] w-[22px] shrink-0 text-primary" />
          {!collapsed && (
            <div className="min-w-0">
              <span className="block truncate text-[14px] font-bold tracking-wide text-foreground">
                Respondr
              </span>
            </div>
          )}
        </div>

        <TooltipProvider delay={0}>
          <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-5">
            {navItems.map((group) => (
              <div key={group.group} className="space-y-2">
                {!collapsed && (
                  <p className="px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-primary">
                    {group.group}
                  </p>
                )}
                <div className="space-y-1">
                  {group.items.map((item) => {
                    const isActive = pathname === item.href;
                    const Icon = item.icon;
                    const linkClasses = `
                      flex items-center gap-3 rounded-lg border border-transparent transition-all duration-150 ease-linear
                      ${collapsed ? 'justify-center px-0 py-3' : 'px-3.5 py-3'}
                      ${
                        isActive
                          ? 'text-foreground font-semibold hover:bg-secondary/50'
                          : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
                      }
                    `;

                    if (collapsed) {
                      return (
                        <Tooltip key={item.href}>
                          <TooltipTrigger render={<Link href={item.href} className={linkClasses} />}>
                            <Icon
                              className={`h-[18px] w-[18px] shrink-0 ${isActive ? 'text-foreground' : ''}`}
                              strokeWidth={1.75}
                            />
                          </TooltipTrigger>
                          <TooltipContent side="right" className="rounded-md border-border text-xs">
                            {item.label}
                          </TooltipContent>
                        </Tooltip>
                      );
                    }

                    return (
                      <Link key={item.href} href={item.href} className={linkClasses}>
                        <span className="truncate text-[13px] font-medium">
                          {item.label}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
        </TooltipProvider>

        <Separator className="bg-sidebar-border/70" />

        <div className="px-3">
          <button
            onClick={toggle}
            className={`mt-3 flex h-11 w-full shrink-0 items-center gap-2 rounded-lg border border-transparent text-muted-foreground transition-colors hover:bg-secondary/50 hover:text-foreground cursor-pointer ${
              collapsed ? 'justify-center' : 'justify-end pr-4 text-right'
            }`}
          >
            {collapsed ? (
              <PanelLeftOpen className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <>
                <span className="text-xs font-medium">Collapse</span>
                <PanelLeftClose className="h-4 w-4" strokeWidth={1.75} />
              </>
            )}
          </button>
        </div>
      </div>
    </aside>
  );
}
