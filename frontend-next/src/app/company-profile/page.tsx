'use client';

import { useEffect, useState } from 'react';
import { AlertCircle, Building2, CheckCircle2, RotateCcw, Save } from 'lucide-react';

import Topbar from '@/components/topbar';
import { PageHeader, PageSection, PageShell } from '@/components/page-shell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { fetchCompanyProfile, saveCompanyProfile } from '@/lib/api';
import type { CompanyProfile } from '@/lib/types';

export default function CompanyProfilePage() {
  const [profile, setProfile] = useState<CompanyProfile>({
    name: '',
    description: '',
    headquarters: '',
    website: '',
  });
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    let active = true;

    (async () => {
      try {
        const nextProfile = await fetchCompanyProfile();
        if (active) setProfile(nextProfile);
      } catch {}
    })();

    return () => {
      active = false;
    };
  }, []);

  const save = async () => {
    setStatus('saving');
    try {
      await saveCompanyProfile(profile);
      setStatus('saved');
      setTimeout(() => setStatus('idle'), 3000);
    } catch {
      setStatus('error');
      setTimeout(() => setStatus('idle'), 3000);
    }
  };

  const reset = async () => {
    try {
      const nextProfile = await fetchCompanyProfile();
      setProfile(nextProfile);
      setStatus('idle');
    } catch {}
  };

  const updateField = (field: keyof CompanyProfile, value: string) => {
    setProfile((previous) => ({ ...previous, [field]: value }));
  };

  return (
    <>
      <Topbar title="Company Profile" />
      <PageShell>
        <PageHeader
          eyebrow="Workspace Setup"
          title="Company Profile"
          description="Maintain the company information used throughout proposal drafts and generated response content."
          actions={
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={reset}>
                <RotateCcw className="mr-2 h-4 w-4" />
                Reset
              </Button>
              <Button onClick={save} disabled={status === 'saving'}>
                <Save className="mr-2 h-4 w-4" />
                {status === 'saving' ? 'Saving...' : 'Save Profile'}
              </Button>
            </div>
          }
        />

        <div className="py-6">
          <PageSection
            title="Organization Details"
            description="These values are used when the app drafts proposals, summaries, and company-specific narrative sections."
          >
            <div className="space-y-5">
              <div className="rounded-2xl border border-border/70 bg-secondary/35 p-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl border border-border/70 bg-card/80 p-2.5">
                    <Building2 className="h-4 w-4 text-primary" strokeWidth={1.75} />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-foreground">Profile usage</p>
                    <p className="text-sm leading-6 text-muted-foreground">
                      Keep this concise and accurate so generated sections sound grounded and reusable across bids.
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid gap-5">
                <div className="space-y-2">
                  <label className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    Company Name
                  </label>
                  <Input
                    value={profile.name}
                    onChange={(event) => updateField('name', event.target.value)}
                    placeholder="Acme Corporation"
                    className="h-11 bg-secondary/40"
                  />
                </div>

                <div className="space-y-2">
                  <label className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    Description
                  </label>
                  <Textarea
                    value={profile.description}
                    onChange={(event) => updateField('description', event.target.value)}
                    rows={5}
                    placeholder="Describe your company, core offerings, and differentiators..."
                    className="min-h-[140px] bg-secondary/40"
                  />
                </div>

                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <label className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Headquarters
                    </label>
                    <Input
                      value={profile.headquarters}
                      onChange={(event) => updateField('headquarters', event.target.value)}
                      placeholder="London, UK"
                      className="h-11 bg-secondary/40"
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Website
                    </label>
                    <Input
                      value={profile.website}
                      onChange={(event) => updateField('website', event.target.value)}
                      placeholder="https://example.com"
                      className="h-11 bg-secondary/40"
                    />
                  </div>
                </div>
              </div>

              {status === 'saved' ? (
                <div className="flex items-center gap-2 rounded-2xl border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-500/12 dark:text-emerald-300">
                  <CheckCircle2 className="h-4 w-4" />
                  Company profile saved successfully.
                </div>
              ) : null}

              {status === 'error' ? (
                <div className="flex items-center gap-2 rounded-2xl border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-400/25 dark:bg-rose-500/12 dark:text-rose-300">
                  <AlertCircle className="h-4 w-4" />
                  We could not save the profile. Please try again.
                </div>
              ) : null}
            </div>
          </PageSection>
        </div>
      </PageShell>
    </>
  );
}
