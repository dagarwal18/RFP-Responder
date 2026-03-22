'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Zap,
  GitBranch,
  FileSearch,
  Library,
  ScrollText,
  Building2,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';

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
    const saved = localStorage.getItem('sidebar-collapsed');
    if (saved === 'true') setCollapsed(true);
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
        sticky top-0 h-screen flex flex-col bg-sidebar border-r border-sidebar-border
        transition-all duration-300 ease-in-out z-50 shrink-0
        ${collapsed ? 'w-16' : 'w-[240px]'}
      `}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 h-14 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center shrink-0">
          <Zap className="w-4 h-4 text-primary" />
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold text-foreground tracking-tight whitespace-nowrap">
            RFP Responder
          </span>
        )}
      </div>

      <Separator className="bg-sidebar-border" />

      {/* Nav */}
      <TooltipProvider delay={0}>
        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-5">
          {navItems.map((group) => (
            <div key={group.group}>
              {!collapsed && (
                <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {group.group}
                </p>
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const isActive = pathname === item.href;
                  const Icon = item.icon;
                  const linkClasses = `
                    flex items-center gap-3 rounded-lg transition-all duration-200 cursor-pointer
                    ${collapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2'}
                    ${
                      isActive
                        ? 'bg-sidebar-primary/15 text-sidebar-primary border border-sidebar-primary/25'
                        : 'text-muted-foreground hover:text-foreground hover:bg-sidebar-accent border border-transparent'
                    }
                  `;

                  if (collapsed) {
                    return (
                      <Tooltip key={item.href}>
                        <TooltipTrigger render={<Link href={item.href} className={linkClasses} />}>
                          <Icon className={`w-[18px] h-[18px] shrink-0 ${isActive ? 'text-sidebar-primary' : ''}`} strokeWidth={1.75} />
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs">
                          {item.label}
                        </TooltipContent>
                      </Tooltip>
                    );
                  }

                  return (
                    <Link key={item.href} href={item.href} className={linkClasses}>
                      <Icon className={`w-[18px] h-[18px] shrink-0 ${isActive ? 'text-sidebar-primary' : ''}`} strokeWidth={1.75} />
                      <span className="text-[13px] font-medium whitespace-nowrap">{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </TooltipProvider>

      <Separator className="bg-sidebar-border" />

      {/* Collapse toggle */}
      <button
        onClick={toggle}
        className="flex items-center justify-center gap-2 h-11 
                   text-muted-foreground hover:text-foreground transition-colors cursor-pointer shrink-0"
      >
        {collapsed ? (
          <PanelLeftOpen className="w-4 h-4" strokeWidth={1.75} />
        ) : (
          <>
            <PanelLeftClose className="w-4 h-4" strokeWidth={1.75} />
            <span className="text-xs">Collapse</span>
          </>
        )}
      </button>
    </aside>
  );
}
