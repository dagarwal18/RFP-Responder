'use client';

import { useState, useEffect, useCallback } from 'react';
import Topbar from '@/components/topbar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { apiFetch, fetchRuns } from '@/lib/api';
import {
  FileSearch, MessageSquare, Check, X, ChevronDown,
} from 'lucide-react';

interface ReviewComment {
  id: string; anchor: string; text: string; severity: string; reviewer: string; created_at: string;
}

interface ReviewData {
  run_id: string; status: string;
  sections: Array<{ title: string; content: string; paragraph_count: number }>;
  comments: ReviewComment[];
  summary: Record<string, string | number>;
}

export default function ReviewPage() {
  const [review, setReview] = useState<ReviewData | null>(null);
  const [reviewer, setReviewer] = useState('');
  const [comments, setComments] = useState<ReviewComment[]>([]);
  const [commentText, setCommentText] = useState('');
  const [commentSeverity, setCommentSeverity] = useState('medium');
  const [selectedAnchor, setSelectedAnchor] = useState<string | null>(null);
  const [showDrawer, setShowDrawer] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const runs = await fetchRuns();
      const r = (runs.runs || []).find(r => r.review_status);
      if (r) { const d = await apiFetch<ReviewData>(`/api/rfp/${r.run_id}/review`); setReview(d); setComments(d.comments || []); }
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const addComment = async () => {
    if (!review || !selectedAnchor || !commentText.trim()) return;
    try {
      await apiFetch(`/api/rfp/${review.run_id}/review/comments`, {
        method: 'POST', body: JSON.stringify({ anchor: selectedAnchor, text: commentText, severity: commentSeverity, reviewer: reviewer || 'Anonymous' }),
      }); setCommentText(''); setSelectedAnchor(null); load();
    } catch {}
  };

  const submitDecision = async (decision: string) => {
    if (!review) return;
    try { await apiFetch(`/api/rfp/${review.run_id}/review/decision`, { method: 'POST', body: JSON.stringify({ decision, reviewer: reviewer || 'Anonymous', summary: '' }) }); load(); } catch {}
  };

  const statusClass = (s: string) => ({ Pending: 'bg-warning/15 text-warning', APPROVED: 'bg-success/15 text-success', REJECTED: 'bg-error/15 text-error', REQUEST_CHANGES: 'bg-info/15 text-info' }[s] || '');

  if (loading) return <><Topbar title="Review" /><div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading…</div></>;

  if (!review) return (
    <><Topbar title="Review" />
      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground text-sm gap-3 p-6">
        <FileSearch className="w-12 h-12 opacity-20" />
        <p>No proposal available for review.</p>
        <p className="text-xs">Run a pipeline first, then come back here.</p>
      </div>
    </>
  );

  return (
    <>
      {/* Review header */}
      <div className="sticky top-0 z-40 flex items-center justify-between px-6 py-3 bg-background/90 backdrop-blur-xl border-b border-border">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <FileSearch className="w-4 h-4 text-primary" strokeWidth={1.75} /> Proposal Review
          </h2>
          <Badge variant="outline" className={`text-[10px] ${statusClass(review.status)}`}>{review.status}</Badge>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Reviewer</label>
            <Input value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="Your name" className="w-40 h-8 text-xs bg-secondary border-border" />
          </div>
          <span className="text-xs text-muted-foreground">{comments.length} comments</span>
        </div>
      </div>

      {/* Summary */}
      {review.summary && Object.keys(review.summary).length > 0 && (
        <div className="max-w-4xl mx-auto px-6 pt-5">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Object.entries(review.summary).map(([k, v]) => (
              <Card key={k} className="bg-card border-border">
                <CardContent className="py-3 px-4">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">{k}</p>
                  <p className="text-lg font-bold text-foreground">{v}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Document */}
      <ScrollArea className="flex-1">
        <div className="max-w-4xl mx-auto px-6 py-8 pb-28 space-y-2">
          {(review.sections || []).map((section, idx) => (
            <details key={idx} className="group border border-border rounded-lg overflow-hidden bg-card/50" open>
              <summary className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none hover:bg-secondary/50 transition-colors border-b border-transparent group-open:border-border">
                <ChevronDown className="w-4 h-4 text-muted-foreground group-open:rotate-0 -rotate-90 transition-transform duration-200 shrink-0" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{section.title}</span>
                <Badge variant="secondary" className="text-[10px] ml-auto">{section.paragraph_count || 1} para</Badge>
              </summary>
              <div className="px-5 py-4" dangerouslySetInnerHTML={{ __html: section.content }}
                onClick={e => {
                  const t = e.target as HTMLElement;
                  if (t.tagName === 'P' || t.closest('p')) {
                    const p = t.tagName === 'P' ? t : t.closest('p')!;
                    setSelectedAnchor(`${section.title} > ¶${Array.from(p.parentElement!.children).indexOf(p) + 1}`);
                  }
                }}
              />
            </details>
          ))}
        </div>
      </ScrollArea>

      {/* Comment popover */}
      {selectedAnchor && (
        <Card className="fixed bottom-24 right-8 z-[200] w-[360px] shadow-2xl animate-in fade-in-0 zoom-in-95">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between w-full">
              <CardTitle className="text-sm">Add Feedback</CardTitle>
              <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer" onClick={() => setSelectedAnchor(null)}><X className="w-4 h-4" /></Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-[11px] text-muted-foreground bg-secondary rounded-md px-2.5 py-1.5 border border-dashed border-border">{selectedAnchor}</p>
            <Textarea value={commentText} onChange={e => setCommentText(e.target.value)} rows={3} placeholder="Describe what needs to change…" className="bg-secondary border-border" />
            <div className="flex items-center gap-2">
              <select value={commentSeverity} onChange={e => setCommentSeverity(e.target.value)} className="px-2.5 py-1.5 rounded-md text-xs bg-secondary border border-border text-foreground">
                <option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option><option value="low">Low</option>
              </select>
              <Button size="sm" className="ml-auto cursor-pointer" onClick={addComment}>Save</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Comments drawer */}
      {showDrawer && (
        <div className="fixed top-0 right-0 w-[400px] h-full z-[180] bg-background/97 backdrop-blur-2xl border-l border-border shadow-[-10px_0_40px_rgba(0,0,0,0.4)] flex flex-col animate-in slide-in-from-right">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <strong className="text-sm">Comments</strong>
            <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer" onClick={() => setShowDrawer(false)}><X className="w-4 h-4" /></Button>
          </div>
          <ScrollArea className="flex-1 px-5 py-4">
            <div className="space-y-3">
              {comments.length === 0 ? <p className="text-sm text-muted-foreground text-center py-8">No comments yet</p> :
                comments.map(c => (
                  <Card key={c.id} className="bg-card border-border">
                    <CardContent className="p-3 space-y-2">
                      <div className="flex items-start justify-between gap-2">
                        <div><p className="text-xs font-semibold">{c.anchor}</p><p className="text-[11px] text-muted-foreground">{c.reviewer}</p></div>
                        <Badge variant="outline" className={`text-[10px] ${c.severity === 'critical' ? 'bg-error/15 text-error' : c.severity === 'high' ? 'bg-warning/15 text-warning' : ''}`}>{c.severity}</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">{c.text}</p>
                    </CardContent>
                  </Card>
                ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* FAB */}
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[160] flex items-center gap-3 px-5 py-3 bg-card/95 backdrop-blur-xl border border-border rounded-2xl shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
        <Button variant="ghost" size="sm" onClick={() => setShowDrawer(!showDrawer)} className="cursor-pointer">
          <MessageSquare className="w-4 h-4 mr-1.5" />{comments.length}
        </Button>
        <Separator orientation="vertical" className="h-6" />
        <Button variant="outline" size="sm" onClick={() => submitDecision('REJECT')} className="text-xs cursor-pointer">Reject</Button>
        <Button variant="outline" size="sm" onClick={() => submitDecision('REQUEST_CHANGES')} className="text-xs cursor-pointer">Request Changes</Button>
        <Button size="sm" onClick={() => submitDecision('APPROVE')} className="text-xs cursor-pointer">
          <Check className="w-3.5 h-3.5 mr-1.5" /> Approve & Finalize
        </Button>
      </div>
    </>
  );
}
