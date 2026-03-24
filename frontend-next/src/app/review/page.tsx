'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Topbar from '@/components/topbar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  fetchReviewPackage,
  fetchRuns,
  saveReviewComments,
  submitReviewDecision,
} from '@/lib/api';
import { FileSearch, MessageSquare, Check, X, ChevronDown } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import mermaid from 'mermaid';

interface ReviewComment {
  comment_id: string;  
  anchor: {
     anchor_level: string;
     domain: string;
     section_id: string;
     section_title: string;
     paragraph_id: string;
     excerpt: string;
  }; 
  comment: string; 
  severity: string; 
  author: string; 
  created_at: string;
}

interface ReviewSection {
  section_id: string;
  title: string;
  domain: string;
  full_text: string;
  paragraphs: Array<{ paragraph_id: string; text: string; }>;
}

interface ReviewPackage {
  review_id: string;
  status: string;
  source_sections: ReviewSection[];
  response_sections: ReviewSection[];
  comments: ReviewComment[];
  commercial_summary: string;
  validation_summary: string;
  legal_summary: string;
}

interface ReviewData {
  rfp_id: string; 
  status: string;
  review_package: ReviewPackage;
}

function Mermaid({ chart }: { chart: string }) {
  const [svg, setSvg] = useState('');
  useEffect(() => {
    mermaid.initialize({ startOnLoad: false, theme: 'default' });
    try {
      mermaid.render('mermaid-' + Math.random().toString(36).substr(2, 9), chart).then(r => setSvg(r.svg)).catch();
    } catch(e) {}
  }, [chart]);
  return <div dangerouslySetInnerHTML={{ __html: svg }} className="my-4 flex justify-center bg-white p-4 rounded text-black" />;
}

function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none text-xs text-muted-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '');
            if (!inline && match && match[1] === 'mermaid') {
              return <Mermaid chart={String(children).replace(/\n$/, '')} />;
            }
            return <code className={className} {...props}>{children}</code>;
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function ReviewContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const explicitRunId = searchParams.get('run_id');

  const [review, setReview] = useState<ReviewData | null>(null);
  const [reviewer, setReviewer] = useState('Approver');
  const [comments, setComments] = useState<ReviewComment[]>([]);
  const [commentText, setCommentText] = useState('');
  const [commentSeverity, setCommentSeverity] = useState('medium');
  
  const [selectedAnchor, setSelectedAnchor] = useState<any>(null); 
  
  const [showDrawer, setShowDrawer] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      let rfpIdToLoad = explicitRunId;
      if (!rfpIdToLoad) {
        const runs = await fetchRuns();
        const r = (runs.runs || []).find((r: any) => r.status === 'AWAITING_HUMAN_VALIDATION' || r.status === 'REVIEW_PENDING');
        if (r) rfpIdToLoad = r.run_id;
      }
      
      if (rfpIdToLoad) {
        const d = await fetchReviewPackage(rfpIdToLoad);
        setReview(d);
        setComments(d.review_package?.comments || []);
      }
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }, [explicitRunId]);

  useEffect(() => { load(); }, [load]);

  const addComment = async () => {
    if (!review || !selectedAnchor || !commentText.trim()) return;
    try {
      const nextComments = [
        ...comments,
        {
          comment_id: `REV-CMT-${Date.now()}`,
          anchor: {
            anchor_level: 'paragraph',
            domain: 'response',
            section_id: selectedAnchor.section_id,
            section_title: selectedAnchor.section_title,
            paragraph_id: selectedAnchor.paragraph_id,
            excerpt: selectedAnchor.excerpt,
          },
          comment: commentText,
          severity: commentSeverity,
          rerun_hint: 'auto',
          status: 'open',
          author: reviewer || 'Anonymous',
          created_at: new Date().toISOString(),
        },
      ];
      const response = await saveReviewComments(review.rfp_id, nextComments);
      setReview(response);
      setComments(response.review_package?.comments || nextComments);
      setCommentText(''); 
      setSelectedAnchor(null); 
    } catch {}
  };

  const submitDecision = async (decision: string) => {
    if (!review) return;
    try { 
      await submitReviewDecision(review.rfp_id, {
        decision,
        reviewer: reviewer || 'Anonymous',
        summary: 'Reviewed via Next.js',
        rerun_from: 'auto',
        comments,
      });
      router.push(`/?run_id=${review.rfp_id}`);
    } catch {}
  };

  const statusClass = (s: string) => ({ Pending: 'bg-warning/15 text-warning', APPROVED: 'bg-success/15 text-success', REJECTED: 'bg-error/15 text-error', CHANGES_REQUESTED: 'bg-info/15 text-info' }[s] || 'bg-secondary text-muted-foreground');

  if (loading) return <><Topbar title="Review Workspace" /><div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading…</div></>;

  if (!review || !review.review_package) return (
    <><Topbar title="Review Workspace" />
      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground text-sm gap-3 p-6">
        <FileSearch className="w-12 h-12 opacity-20" />
        <p>No proposal available for review.</p>
        <p className="text-xs">Wait for a pipeline to reach Human Validation.</p>
      </div>
    </>
  );

  const rp = review.review_package;

  return (
    <>
      <Topbar title="Review Workspace" />
      {/* Header */}
      <div className="sticky top-0 z-40 flex items-center justify-between px-6 py-3 bg-background/90 backdrop-blur-xl border-b border-border">
        <div className="flex items-center gap-3">
          <h2 className="text-[13px] font-semibold flex items-center gap-2">
             Proposal: {review.rfp_id}
          </h2>
          <Badge variant="outline" className={`text-[10px] ${statusClass(rp.status)}`}>{rp.status}</Badge>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Reviewer</label>
            <Input value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="Your name" className="w-40 h-8 text-xs bg-secondary border-border" />
          </div>
          <span className="text-[11px] text-muted-foreground">{comments.length} comments</span>
        </div>
      </div>

      {/* Summary */}
      <div className="max-w-4xl mx-auto px-6 pt-5">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Card className="bg-card border-border">
              <CardContent className="py-3 px-4">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">Commercial Review</p>
                <p className="text-[11px] text-foreground">{rp.commercial_summary || 'Approved with standard pricing.'}</p>
              </CardContent>
            </Card>
            <Card className="bg-card border-border">
              <CardContent className="py-3 px-4">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">Legal Review</p>
                <p className="text-[11px] text-foreground">{rp.legal_summary || 'No critical risks identified.'}</p>
              </CardContent>
            </Card>
            <Card className="bg-card border-border">
              <CardContent className="py-3 px-4">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">Technical Review</p>
                <p className="text-[11px] text-foreground">{rp.validation_summary || 'All functional requirements met.'}</p>
              </CardContent>
            </Card>
        </div>
      </div>

      {/* Document */}
      <ScrollArea className="flex-1">
        <div className="max-w-4xl mx-auto px-6 py-8 pb-32 space-y-4">
          <h3 className="text-sm font-bold border-b border-border pb-2">Response Document</h3>
          {(rp.response_sections || []).map((section, idx) => (
            <details key={idx} className="group border border-border rounded-lg overflow-hidden bg-card/50" open>
              <summary className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none hover:bg-secondary/50 transition-colors border-b border-transparent group-open:border-border">
                <ChevronDown className="w-4 h-4 text-muted-foreground group-open:rotate-0 -rotate-90 transition-transform duration-200 shrink-0" />
                <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">{section.title}</span>
                <Badge variant="secondary" className="text-[10px] ml-auto">{section.paragraphs?.length || 1} para</Badge>
              </summary>
              <div className="px-5 py-4 space-y-4">
                {section.paragraphs?.length > 0 ? (
                  section.paragraphs.map(p => (
                     <div 
                        key={p.paragraph_id} 
                        className="group/para cursor-pointer hover:bg-secondary/50 p-2 -mx-2 rounded transition-colors"
                        onClick={() => setSelectedAnchor({
                          section_id: section.section_id,
                          section_title: section.title,
                          paragraph_id: p.paragraph_id,
                          excerpt: p.text.substring(0, 50) + '...'
                        })}
                     >
                       <MarkdownRenderer content={p.text} />
                     </div>
                  ))
                ) : (
                  <MarkdownRenderer content={section.full_text || 'No content provided.'} />
                )}
              </div>
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
            <p className="text-[10px] text-muted-foreground bg-secondary rounded-md px-2.5 py-1.5 border border-dashed border-border flex flex-col gap-1">
               <strong>{selectedAnchor.section_title} &gt; {selectedAnchor.paragraph_id.split('-').pop()}</strong>
               <span>"{selectedAnchor.excerpt}"</span>
            </p>
            <Textarea value={commentText} onChange={e => setCommentText(e.target.value)} rows={3} placeholder="Describe what needs to change…" className="bg-secondary border-border text-xs" />
            <div className="flex items-center gap-2">
              <select value={commentSeverity} onChange={e => setCommentSeverity(e.target.value)} className="px-2.5 py-1.5 rounded-md text-xs bg-secondary border border-border text-foreground">
                <option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option><option value="low">Low</option>
              </select>
              <Button size="sm" className="ml-auto cursor-pointer text-xs" onClick={addComment}>Save Comment</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Comments drawer */}
      {showDrawer && (
        <div className="fixed top-0 right-0 w-[400px] h-full z-[180] bg-background/97 backdrop-blur-2xl border-l border-border shadow-[-10px_0_40px_rgba(0,0,0,0.4)] flex flex-col animate-in slide-in-from-right">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <strong className="text-sm">Comments & Feedback</strong>
            <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer" onClick={() => setShowDrawer(false)}><X className="w-4 h-4" /></Button>
          </div>
          <ScrollArea className="flex-1 px-5 py-4">
            <div className="space-y-3">
              {comments.length === 0 ? <p className="text-sm text-muted-foreground text-center py-8">No comments yet</p> :
                comments.map(c => (
                  <Card key={c.comment_id} className="bg-card border-border">
                    <CardContent className="p-3 space-y-2">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                           <p className="text-[11px] font-semibold">{c.anchor?.section_title} {c.anchor?.paragraph_id ? `> ${c.anchor.paragraph_id.split('-').pop()}` : ''}</p>
                           <p className="text-[10px] text-muted-foreground">{c.author}</p>
                        </div>
                        <Badge variant="outline" className={`text-[9px] uppercase ${c.severity === 'critical' ? 'bg-error/15 text-error border-error/20' : c.severity === 'high' ? 'bg-warning/15 text-warning border-warning/20' : ''}`}>{c.severity}</Badge>
                      </div>
                      <p className="text-[11px] text-muted-foreground bg-secondary/50 p-1.5 rounded italic break-all">"{c.anchor?.excerpt}"</p>
                      <p className="text-[11px] text-foreground mt-1">{c.comment}</p>
                    </CardContent>
                  </Card>
                ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* FAB - Actions */}
      {rp.status === 'PENDING' && (
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[160] flex items-center gap-3 px-5 py-3 bg-card/95 backdrop-blur-xl border border-border rounded-2xl shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
        <Button variant="ghost" size="sm" onClick={() => setShowDrawer(!showDrawer)} className="cursor-pointer">
          <MessageSquare className="w-4 h-4 mr-1.5" />{comments.length}
        </Button>
        <Separator orientation="vertical" className="h-6" />
        <Button variant="outline" size="sm" onClick={() => submitDecision('REJECT')} className="text-xs cursor-pointer text-error hover:text-error hover:bg-error/10">Reject</Button>
        <Button variant="outline" size="sm" onClick={() => submitDecision('REQUEST_CHANGES')} className="text-xs cursor-pointer text-info hover:text-info hover:bg-info/10">Request Changes</Button>
        <Button size="sm" onClick={() => submitDecision('APPROVE')} className="text-xs cursor-pointer bg-success text-success-foreground hover:bg-success/90">
          <Check className="w-3.5 h-3.5 mr-1.5" /> Approve & Submit
        </Button>
      </div>)}
    </>
  );
}

export default function ReviewPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ReviewContent />
    </Suspense>
  )
}
