'use client';

import { useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, ScrollText, Trash2, X } from 'lucide-react';

import Topbar from '@/components/topbar';
import { PageHeader, PageSection, PageShell, PageStat, PageStatGrid } from '@/components/page-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  createPolicy,
  deleteAllPolicies,
  deletePolicy,
  fetchPolicies,
  updatePolicy,
} from '@/lib/api';
import type { Policy } from '@/lib/types';

const POLICY_CATEGORIES = [
  'capability',
  'certification',
  'legal',
  'compliance',
  'operational',
  'commercial',
  'governance',
];

const POLICY_SEVERITIES = ['medium', 'critical', 'high', 'low'];

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [filterCat, setFilterCat] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({
    text: '',
    category: 'capability',
    severity: 'medium',
    source_section: '',
  });

  useEffect(() => {
    let active = true;

    (async () => {
      try {
        const data = await fetchPolicies();
        if (active) setPolicies(data.policies || []);
      } catch {}
    })();

    return () => {
      active = false;
    };
  }, []);

  const reloadPolicies = async () => {
    try {
      const data = await fetchPolicies();
      setPolicies(data.policies || []);
    } catch {}
  };

  const openAdd = () => {
    setEditId(null);
    setForm({ text: '', category: 'capability', severity: 'medium', source_section: '' });
    setModalOpen(true);
  };

  const openEdit = (policy: Policy) => {
    setEditId(policy.id);
    setForm({
      text: policy.text,
      category: policy.category,
      severity: policy.severity,
      source_section: policy.source_section || '',
    });
    setModalOpen(true);
  };

  const save = async () => {
    try {
      if (editId) {
        await updatePolicy(editId, form);
      } else {
        await createPolicy(form);
      }
      setModalOpen(false);
      reloadPolicies();
    } catch {}
  };

  const remove = async (id: string) => {
    try {
      await deletePolicy(id);
      reloadPolicies();
    } catch {}
  };

  const removeAll = async () => {
    try {
      await deleteAllPolicies();
      reloadPolicies();
    } catch {}
  };

  const severityClass = (value: string) =>
    ({
      critical:
        'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-400/25 dark:bg-rose-500/12 dark:text-rose-300',
      high: 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-400/25 dark:bg-amber-500/12 dark:text-amber-300',
      medium: 'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-400/25 dark:bg-sky-500/12 dark:text-sky-300',
      low: 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-500/12 dark:text-emerald-300',
    }[value] || '');

  const categoryClass = (value: string) =>
    ({
      capability: 'border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-400/25 dark:bg-orange-500/12 dark:text-orange-300',
      legal: 'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-400/25 dark:bg-rose-500/12 dark:text-rose-300',
      certification: 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-500/12 dark:text-emerald-300',
      compliance: 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-400/25 dark:bg-amber-500/12 dark:text-amber-300',
      operational: 'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-400/25 dark:bg-sky-500/12 dark:text-sky-300',
      commercial: 'border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-400/25 dark:bg-violet-500/12 dark:text-violet-300',
      governance: 'border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-400/25 dark:bg-slate-500/12 dark:text-slate-300',
    }[value] || '');

  const filteredPolicies = filterCat
    ? policies.filter((policy) => policy.category === filterCat)
    : policies;

  const criticalCount = useMemo(
    () => policies.filter((policy) => policy.severity === 'critical').length,
    [policies]
  );

  const categoryCount = useMemo(() => new Set(policies.map((policy) => policy.category)).size, [policies]);

  return (
    <>
      <Topbar title="Policies" />
      <PageShell>
        <PageHeader
          eyebrow="Manage"
          title="Policy Library"
          description="Maintain reusable constraints and policy signals that shape drafting, validation, and review behavior."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={removeAll}>
                <Trash2 className="mr-2 h-4 w-4" />
                Clear All
              </Button>
              <Button onClick={openAdd}>
                <Plus className="mr-2 h-4 w-4" />
                Add Policy
              </Button>
            </div>
          }
        />

        <div className="space-y-6 py-6">
          <PageStatGrid className="xl:grid-cols-3">
            <PageStat
              label="Total Policies"
              value={policies.length}
              detail="All reusable drafting and validation rules."
            />
            <PageStat
              label="Categories"
              value={categoryCount}
              detail="Distinct policy groups currently represented."
            />
            <PageStat
              label="Critical Items"
              value={criticalCount}
              detail="Highest-severity rules that deserve closer review."
            />
          </PageStatGrid>

          <PageSection
            title="Policy Table"
            description="Filter by category, review the active rule set, and edit individual items inline from this table."
            actions={
              <select
                value={filterCat}
                onChange={(event) => setFilterCat(event.target.value)}
                className="h-10 rounded-xl border border-border bg-secondary/45 px-3 text-sm text-foreground outline-none"
              >
                <option value="">All categories</option>
                {POLICY_CATEGORIES.map((category) => (
                  <option key={category} value={category}>
                    {category.charAt(0).toUpperCase() + category.slice(1)}
                  </option>
                ))}
              </select>
            }
            contentClassName="p-0"
          >
            {filteredPolicies.length === 0 ? (
              <div className="px-5 py-14 text-center">
                <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl border border-border/70 bg-secondary/35">
                  <ScrollText className="h-5 w-5 text-muted-foreground" />
                </div>
                <p className="text-sm font-medium text-foreground">No policies match this view.</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Add a policy or change the category filter to see more results.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead className="bg-secondary/30">
                    <tr className="border-b border-border/70 text-left">
                      <th className="px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                        Policy
                      </th>
                      <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                        Category
                      </th>
                      <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                        Severity
                      </th>
                      <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                        Source
                      </th>
                      <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPolicies.map((policy) => (
                      <tr
                        key={policy.id}
                        className="border-b border-border/60 transition hover:bg-secondary/20"
                      >
                        <td className="px-5 py-4 text-sm leading-6 text-foreground/90">
                          {policy.text}
                        </td>
                        <td className="px-4 py-4">
                          <Badge variant="outline" className={categoryClass(policy.category)}>
                            {policy.category}
                          </Badge>
                        </td>
                        <td className="px-4 py-4">
                          <Badge variant="outline" className={severityClass(policy.severity)}>
                            {policy.severity}
                          </Badge>
                        </td>
                        <td className="px-4 py-4 text-sm text-muted-foreground">
                          {policy.source_section || 'Not specified'}
                        </td>
                        <td className="px-4 py-4">
                          <div className="flex items-center gap-2">
                            <Button variant="outline" size="sm" onClick={() => openEdit(policy)}>
                              <Pencil className="mr-1.5 h-3.5 w-3.5" />
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-rose-600 hover:bg-rose-500/10 hover:text-rose-700 dark:text-rose-300 dark:hover:text-rose-200"
                              onClick={() => remove(policy.id)}
                            >
                              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                              Delete
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </PageSection>
        </div>
      </PageShell>

      {modalOpen ? (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <Card className="w-full max-w-lg rounded-3xl border-border/70 bg-background/98 shadow-[0_28px_80px_rgba(0,0,0,0.22)]">
            <CardHeader className="border-b border-border/70 pb-4">
              <div className="flex items-center justify-between gap-3">
                <div className="space-y-1">
                  <CardTitle className="text-lg font-semibold text-foreground">
                    {editId ? 'Edit Policy' : 'Add Policy'}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Capture reusable guidance that the drafting and validation steps should respect.
                  </p>
                </div>
                <Button variant="ghost" size="icon-sm" onClick={() => setModalOpen(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 py-5">
              <Textarea
                value={form.text}
                onChange={(event) => setForm((previous) => ({ ...previous, text: event.target.value }))}
                placeholder="Write the policy text..."
                rows={4}
                className="min-h-[140px] bg-secondary/40"
              />

              <div className="grid gap-4 sm:grid-cols-2">
                <select
                  value={form.category}
                  onChange={(event) =>
                    setForm((previous) => ({ ...previous, category: event.target.value }))
                  }
                  className="h-11 rounded-xl border border-border bg-secondary/40 px-3 text-sm text-foreground outline-none"
                >
                  {POLICY_CATEGORIES.map((category) => (
                    <option key={category} value={category}>
                      {category.charAt(0).toUpperCase() + category.slice(1)}
                    </option>
                  ))}
                </select>

                <select
                  value={form.severity}
                  onChange={(event) =>
                    setForm((previous) => ({ ...previous, severity: event.target.value }))
                  }
                  className="h-11 rounded-xl border border-border bg-secondary/40 px-3 text-sm text-foreground outline-none"
                >
                  {POLICY_SEVERITIES.map((severity) => (
                    <option key={severity} value={severity}>
                      {severity.charAt(0).toUpperCase() + severity.slice(1)}
                    </option>
                  ))}
                </select>
              </div>

              <Input
                value={form.source_section}
                onChange={(event) =>
                  setForm((previous) => ({ ...previous, source_section: event.target.value }))
                }
                placeholder="Source section (optional)"
                className="h-11 bg-secondary/40"
              />

              <div className="flex justify-end gap-2 pt-1">
                <Button variant="outline" onClick={() => setModalOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={save}>Save Policy</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}
