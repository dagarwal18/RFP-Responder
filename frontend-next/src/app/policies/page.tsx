'use client';

import { useState, useEffect, useCallback } from 'react';
import Topbar from '@/components/topbar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import { apiFetch, fetchPolicies } from '@/lib/api';
import type { Policy } from '@/lib/types';
import { ScrollText, Plus, Trash2, Pencil, X } from 'lucide-react';

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [filterCat, setFilterCat] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({ text: '', category: 'capability', severity: 'medium', source_section: '' });

  const load = useCallback(async () => { try { const d = await fetchPolicies(); setPolicies(d.policies || []); } catch {} }, []);
  useEffect(() => { load(); }, [load]);

  const openAdd = () => { setEditId(null); setForm({ text: '', category: 'capability', severity: 'medium', source_section: '' }); setModalOpen(true); };
  const openEdit = (p: Policy) => { setEditId(p.id); setForm({ text: p.text, category: p.category, severity: p.severity, source_section: p.source_section || '' }); setModalOpen(true); };

  const save = async () => {
    try {
      if (editId) await apiFetch(`/api/knowledge/policies/${editId}`, { method: 'PUT', body: JSON.stringify(form) });
      else await apiFetch('/api/knowledge/policies', { method: 'POST', body: JSON.stringify(form) });
      setModalOpen(false); load();
    } catch {}
  };

  const del = async (id: string) => { try { await apiFetch(`/api/knowledge/policies/${id}`, { method: 'DELETE' }); load(); } catch {} };
  const delAll = async () => { try { await apiFetch('/api/knowledge/policies', { method: 'DELETE' }); load(); } catch {} };

  const sevClass = (s: string) => ({ critical: 'bg-error/15 text-error', high: 'bg-warning/15 text-warning', medium: 'bg-info/15 text-info', low: '' }[s] || '');
  const catClass = (c: string) => ({ capability: 'bg-primary/15 text-primary', legal: 'bg-error/15 text-error', certification: 'bg-success/15 text-success', compliance: 'bg-warning/15 text-warning', operational: 'bg-info/15 text-info' }[c] || '');

  const filtered = filterCat ? policies.filter(p => p.category === filterCat) : policies;

  return (
    <>
      <Topbar title="Policies" />
      <ScrollArea className="flex-1">
        <div className="p-6 max-w-5xl mx-auto w-full">
          <Card className="bg-card border-border">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between w-full">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <ScrollText className="w-4 h-4 text-primary" strokeWidth={1.75} />
                  Policies
                  <Badge variant="secondary" className="text-[10px] ml-1">{policies.length}</Badge>
                </CardTitle>
                <div className="flex items-center gap-2">
                  <select value={filterCat} onChange={e => setFilterCat(e.target.value)} className="px-2.5 py-1.5 rounded-md text-xs bg-secondary border border-border text-foreground">
                    <option value="">All</option>
                    {['certification', 'legal', 'compliance', 'operational', 'commercial', 'governance', 'capability'].map(c => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
                  </select>
                  <Button size="sm" onClick={openAdd} className="cursor-pointer"><Plus className="w-3 h-3 mr-1.5" /> Add Policy</Button>
                  <Button variant="outline" size="icon" className="h-8 w-8 text-destructive border-destructive/40 hover:bg-destructive/10 cursor-pointer" onClick={delAll}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {filtered.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground text-sm">No policies. Add one above.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b-2 border-border text-left">
                        <th className="px-6 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-[40%]">Policy</th>
                        <th className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Category</th>
                        <th className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Severity</th>
                        <th className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Source</th>
                        <th className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-20">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {filtered.map((p, i) => (
                        <tr key={`${p.id}-${i}`} className="hover:bg-secondary/30 transition-colors">
                          <td className="px-6 py-3 text-muted-foreground text-xs leading-relaxed">{p.text}</td>
                          <td className="px-3 py-3"><Badge variant="outline" className={`text-[10px] ${catClass(p.category)}`}>{p.category}</Badge></td>
                          <td className="px-3 py-3"><Badge variant="outline" className={`text-[10px] ${sevClass(p.severity)}`}>{p.severity}</Badge></td>
                          <td className="px-3 py-3 text-xs text-muted-foreground">{p.source_section || '—'}</td>
                          <td className="px-3 py-3">
                            <div className="flex gap-1">
                              <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer" onClick={() => openEdit(p)}><Pencil className="w-3.5 h-3.5" /></Button>
                              <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive cursor-pointer" onClick={() => del(p.id)}><Trash2 className="w-3.5 h-3.5" /></Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </ScrollArea>

      {modalOpen && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <Card className="w-full max-w-md shadow-2xl animate-in fade-in-0 zoom-in-95">
            <CardHeader>
              <div className="flex items-center justify-between w-full">
                <CardTitle className="text-sm">{editId ? 'Edit Policy' : 'Add Policy'}</CardTitle>
                <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer" onClick={() => setModalOpen(false)}><X className="w-4 h-4" /></Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea value={form.text} onChange={e => setForm(f => ({ ...f, text: e.target.value }))} placeholder="Policy text…" rows={3} className="bg-secondary border-border" />
              <div className="grid grid-cols-2 gap-3">
                <select value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} className="px-3 py-2 rounded-md text-xs bg-secondary border border-border text-foreground">
                  {['capability', 'certification', 'legal', 'compliance', 'operational', 'commercial', 'governance'].map(c => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
                </select>
                <select value={form.severity} onChange={e => setForm(f => ({ ...f, severity: e.target.value }))} className="px-3 py-2 rounded-md text-xs bg-secondary border border-border text-foreground">
                  {['medium', 'critical', 'high', 'low'].map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
                </select>
              </div>
              <Input value={form.source_section} onChange={e => setForm(f => ({ ...f, source_section: e.target.value }))} placeholder="Source section (optional)" className="bg-secondary border-border" />
              <div className="flex justify-end gap-2 pt-1">
                <Button variant="outline" size="sm" onClick={() => setModalOpen(false)} className="cursor-pointer">Cancel</Button>
                <Button size="sm" onClick={save} className="cursor-pointer">Save</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
