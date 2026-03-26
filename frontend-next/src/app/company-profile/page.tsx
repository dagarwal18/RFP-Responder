'use client';

import { useEffect, useState } from 'react';
import { Pencil, Save, X } from 'lucide-react';

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
  const [isEditing, setIsEditing] = useState(false);

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
      setIsEditing(false);
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
      setIsEditing(false);
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
            !isEditing ? (
              <Button onClick={() => setIsEditing(true)} className="h-8 rounded-none bg-primary text-primary-foreground text-[11px] uppercase tracking-wider font-bold hover:bg-primary/90">
                <Pencil className="mr-2 h-3 w-3" />
                Edit Profile
              </Button>
            ) : (
              <div className="flex items-center gap-4">
                {status === 'saved' && (
                  <span className="text-[11px] font-bold uppercase tracking-widest text-success">Saved Successfully</span>
                )}
                {status === 'error' && (
                  <span className="text-[11px] font-bold uppercase tracking-widest text-error">Save Failed</span>
                )}
                <Button variant="outline" onClick={reset} className="h-8 rounded-none border-border text-[11px] uppercase tracking-wider font-bold">
                  <X className="mr-2 h-3 w-3" />
                  Cancel
                </Button>
                <Button onClick={save} disabled={status === 'saving'} className="h-8 rounded-none bg-primary text-primary-foreground text-[11px] uppercase tracking-wider font-bold hover:bg-primary/90">
                  <Save className="mr-2 h-3 w-3" />
                  {status === 'saving' ? 'Saving...' : 'Save Profile'}
                </Button>
              </div>
            )
          }
        />

        <div className="py-0">
          <PageSection
            title="Organization Details"
            description="These values are used when the app drafts proposals, summaries, and company-specific narrative sections."
            className="border-none"
            contentClassName="px-0 py-6"
          >
            <div className="max-w-2xl">
              <div className="grid gap-6">
                <div>
                  <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2 block">
                    Company Name
                  </label>
                  {!isEditing ? (
                    <div className="text-sm font-medium text-foreground">{profile.name || 'Not specified'}</div>
                  ) : (
                    <Input
                      value={profile.name}
                      onChange={(event) => updateField('name', event.target.value)}
                      placeholder="Acme Corporation"
                      className="rounded-sm border-border bg-transparent shadow-none h-9 text-sm"
                    />
                  )}
                </div>

                <div>
                  <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2 block">
                    Description
                  </label>
                  {!isEditing ? (
                    <div className="text-sm text-foreground whitespace-pre-wrap leading-6">{profile.description || 'Not specified'}</div>
                  ) : (
                    <Textarea
                      value={profile.description}
                      onChange={(event) => updateField('description', event.target.value)}
                      rows={4}
                      placeholder="Describe your company, core offerings, and differentiators..."
                      className="min-h-[100px] rounded-sm border-border bg-transparent shadow-none resize-y text-sm"
                    />
                  )}
                </div>

                <div className="grid md:grid-cols-2 gap-6">
                  <div>
                    <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2 block">
                      Headquarters
                    </label>
                    {!isEditing ? (
                      <div className="text-sm font-medium text-foreground">{profile.headquarters || 'Not specified'}</div>
                    ) : (
                      <Input
                        value={profile.headquarters}
                        onChange={(event) => updateField('headquarters', event.target.value)}
                        placeholder="London, UK"
                        className="rounded-sm border-border bg-transparent shadow-none h-9 text-sm"
                      />
                    )}
                  </div>

                  <div>
                    <label className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2 block">
                      Website
                    </label>
                    {!isEditing ? (
                      <div className="text-sm font-medium text-primary">{profile.website || 'Not specified'}</div>
                    ) : (
                      <Input
                        value={profile.website}
                        onChange={(event) => updateField('website', event.target.value)}
                        placeholder="https://example.com"
                        className="rounded-sm border-border bg-transparent shadow-none h-9 text-sm"
                      />
                    )}
                  </div>
                </div>
              </div>
            </div>
          </PageSection>
        </div>
      </PageShell>
    </>
  );
}
