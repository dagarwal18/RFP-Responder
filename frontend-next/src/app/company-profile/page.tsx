'use client';

import { useState, useEffect, useCallback } from 'react';
import Topbar from '@/components/topbar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { apiFetch, fetchCompanyProfile } from '@/lib/api';
import type { CompanyProfile } from '@/lib/types';
import { Building2, Save, RotateCcw, CheckCircle2, AlertCircle } from 'lucide-react';

export default function CompanyProfilePage() {
  const [profile, setProfile] = useState<CompanyProfile>({ name: '', description: '', headquarters: '', website: '' });
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const load = useCallback(async () => { try { setProfile(await fetchCompanyProfile()); } catch {} }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setStatus('saving');
    try { await apiFetch('/api/knowledge/company-profile', { method: 'PUT', body: JSON.stringify(profile) }); setStatus('saved'); setTimeout(() => setStatus('idle'), 3000); }
    catch { setStatus('error'); setTimeout(() => setStatus('idle'), 3000); }
  };

  const u = (f: keyof CompanyProfile, v: string) => setProfile(p => ({ ...p, [f]: v }));

  return (
    <>
      <Topbar title="Company Profile" />
      <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto w-full">
        <Card className="bg-card border-border">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <Building2 className="w-4 h-4 text-primary" strokeWidth={1.75} />
              Company Profile
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="text-xs text-muted-foreground">
              Your company details used in proposal documents. Changes are saved to the database.
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Company Name</label>
                <Input value={profile.name} onChange={e => u('name', e.target.value)} placeholder="e.g. Acme Corp" className="bg-secondary border-border" />
              </div>
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Description</label>
                <Textarea value={profile.description} onChange={e => u('description', e.target.value)} rows={4} placeholder="Brief description…" className="bg-secondary border-border" />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Headquarters</label>
                  <Input value={profile.headquarters} onChange={e => u('headquarters', e.target.value)} placeholder="e.g. London, UK" className="bg-secondary border-border" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Website</label>
                  <Input value={profile.website} onChange={e => u('website', e.target.value)} placeholder="e.g. https://example.com" className="bg-secondary border-border" />
                </div>
              </div>
            </div>

            {status === 'saved' && (
              <div className="flex items-center gap-2 text-xs text-success bg-success/10 border border-success/20 rounded-md px-3 py-2">
                <CheckCircle2 className="w-3.5 h-3.5" /> Profile saved successfully
              </div>
            )}
            {status === 'error' && (
              <div className="flex items-center gap-2 text-xs text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
                <AlertCircle className="w-3.5 h-3.5" /> Failed to save profile
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={load} className="cursor-pointer">
                <RotateCcw className="w-3.5 h-3.5 mr-2" /> Reset
              </Button>
              <Button onClick={save} disabled={status === 'saving'} className="cursor-pointer">
                <Save className="w-3.5 h-3.5 mr-2" /> {status === 'saving' ? 'Saving…' : 'Save Profile'}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
