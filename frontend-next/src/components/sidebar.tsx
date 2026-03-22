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
  GitBranch,
  FileSearch,
  Library,
  ScrollText,
  Building2,
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
        transition-all duration-100 ease-linear z-50 shrink-0
        ${collapsed ? 'w-16' : 'w-[240px]'}
      `}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 h-14 border-b border-sidebar-border shrink-0">
        <BrandLogo className="w-[22px] h-[22px] text-foreground shrink-0" />
        {!collapsed && (
          <span className="text-[13px] font-bold text-foreground tracking-[0.1em] whitespace-nowrap uppercase">
            RFP Responder
          </span>
        )}
      </div>

      {/* Nav */}
      <TooltipProvider delay={0}>
        <nav className="flex-1 overflow-y-auto py-6 flex flex-col gap-6">
          {navItems.map((group) => (
            <div key={group.group}>
              {!collapsed && (
                <p className="px-5 mb-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {group.group}
                </p>
              )}
              <div className="flex flex-col">
                {group.items.map((item) => {
                  const isActive = pathname === item.href;
                  const Icon = item.icon;
                  const linkClasses = `
                    flex items-center gap-3 transition-colors duration-100 ease-linear cursor-pointer border-l-[3px]
                    ${collapsed ? 'justify-center px-0 py-3' : 'px-5 py-2.5'}
                    ${
                      isActive
                        ? 'text-foreground border-primary bg-sidebar-accent/50'
                        : 'text-muted-foreground hover:text-foreground hover:bg-sidebar-accent/30 border-transparent'
                    }
                  `;

                  if (collapsed) {
                    return (
                      <Tooltip key={item.href}>
                        <TooltipTrigger render={<Link href={item.href} className={linkClasses} />}>
                          <Icon className={`w-[18px] h-[18px] shrink-0 ${isActive ? 'text-primary' : ''}`} strokeWidth={1.75} />
                        </TooltipTrigger>
                        <TooltipContent side="right" className="text-xs rounded-none border-border">
                          {item.label}
                        </TooltipContent>
                      </Tooltip>
                    );
                  }

                  return (
                    <Link key={item.href} href={item.href} className={linkClasses}>
                      <span className={`text-[13px] font-medium whitespace-nowrap ${isActive ? 'text-primary' : ''}`}>{item.label}</span>
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
