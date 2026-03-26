'use client';

import { Suspense, useCallback, useEffect, useRef, useState, useId } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import mermaid from 'mermaid';
import {
  Check,
  ChevronDown,
  Crosshair,
  FileSearch,
  MessageSquare,
  Plus,
  Trash2,
  X,
} from 'lucide-react';

import Topbar from '@/components/topbar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import {
  fetchReviewPackage,
  fetchRuns,
  saveReviewComments,
  submitReviewDecision,
} from '@/lib/api';
import { cn } from '@/lib/utils';

type ReviewDecision = 'APPROVE' | 'REQUEST_CHANGES' | 'REJECT';
type ReviewSeverity = 'low' | 'medium' | 'high' | 'critical';

interface ReviewAnchor {
  anchor_level: string;
  domain: string;
  section_id: string;
  section_title: string;
  paragraph_id: string;
  excerpt: string;
}

interface ReviewComment {
  comment_id: string;
  anchor: ReviewAnchor;
  comment: string;
  severity: string;
  author: string;
  created_at: string;
}

interface ReviewParagraph {
  paragraph_id: string;
  text: string;
}

interface ReviewSection {
  section_id: string;
  title: string;
  domain: string;
  full_text: string;
  paragraphs: ReviewParagraph[];
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
  open_comment_count?: number;
  decision?: {
    reviewer?: string;
    summary?: string;
  };
}

interface ReviewData {
  rfp_id: string;
  status: string;
  review_package: ReviewPackage;
}

interface PopoverPosition {
  left: number;
  top: number;
}

function normalizeReviewStatus(value = '') {
  const raw = String(value || '').trim();
  if (!raw) return '';
  return raw.split('.').pop()?.toUpperCase() || '';
}

function humanizeStatus(value = '') {
  return (normalizeReviewStatus(value) || 'PENDING').replace(/_/g, ' ');
}

function formatParagraphLabel(paragraphId: string, fallbackIndex: number) {
  const suffix = paragraphId.split('-').pop()?.trim();
  if (!suffix) return `Para ${fallbackIndex + 1}`;
  if (/^\d+$/.test(suffix)) return `Para ${suffix}`;
  return suffix.toUpperCase();
}

function truncateText(value = '', max = 160) {
  const clean = String(value || '').replace(/\s+/g, ' ').trim();
  if (!clean) return '';
  return clean.length > max ? `${clean.slice(0, max).trimEnd()}...` : clean;
}

function anchorKey(anchor: Pick<ReviewAnchor, 'domain' | 'section_id' | 'paragraph_id'>) {
  return `${anchor.domain}::${anchor.section_id}::${anchor.paragraph_id || '__section__'}`;
}

function formatAnchorLabel(anchor: ReviewAnchor | null) {
  if (!anchor) return 'Select a paragraph to leave feedback.';
  const bits = [
    anchor.domain === 'source' ? 'Source' : 'Response',
    anchor.section_title || anchor.section_id || 'Section',
  ];
  if (anchor.paragraph_id) bits.push(formatParagraphLabel(anchor.paragraph_id, 0));
  return bits.join(' / ');
}

function buildAnchor(section: ReviewSection, paragraph?: ReviewParagraph): ReviewAnchor {
  const excerpt = paragraph?.text || section.full_text || '';
  return {
    anchor_level: paragraph ? 'paragraph' : 'section',
    domain: section.domain || 'response',
    section_id: section.section_id,
    section_title: section.title || section.section_id,
    paragraph_id: paragraph?.paragraph_id || '',
    excerpt: truncateText(excerpt, 220),
  };
}

function statusBadgeClass(value = '') {
  const normalized = normalizeReviewStatus(value);
  if (normalized === 'APPROVED' || normalized === 'COMPLETED' || normalized === 'SUBMITTED') {
    return 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-500/12 dark:text-emerald-300';
  }
  if (normalized === 'REQUEST_CHANGES' || normalized === 'CHANGES_REQUESTED') {
    return 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-400/25 dark:bg-amber-500/12 dark:text-amber-300';
  }
  if (normalized === 'REJECTED') {
    return 'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-400/25 dark:bg-rose-500/12 dark:text-rose-300';
  }
  return 'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-400/20 dark:bg-sky-500/10 dark:text-sky-200';
}

function severityBadgeClass(value = 'medium') {
  switch (String(value).toLowerCase()) {
    case 'critical':
      return 'border-rose-400/30 bg-rose-500/12 text-rose-300';
    case 'high':
      return 'border-orange-400/30 bg-orange-500/12 text-orange-300';
    case 'low':
      return 'border-sky-400/25 bg-sky-500/12 text-sky-300';
    default:
      return 'border-amber-400/25 bg-amber-500/12 text-amber-300';
  }
}

function Mermaid({ chart }: { chart: string }) {
  const [svg, setSvg] = useState('');
  const [error, setError] = useState('');
  const renderId = useId().replace(/:/g, '-');

  useEffect(() => {
    let cancelled = false;

    async function renderChart() {
      const source = chart.trim();
      if (!source) {
        setSvg('');
        setError('Empty Mermaid diagram');
        return;
      }

      mermaid.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'loose',
      });

      try {
        const result = await mermaid.render(`mermaid-${renderId}`, source);
        if (!cancelled) {
          setSvg(result.svg);
          setError('');
        }
      } catch (err) {
        if (!cancelled) {
          setSvg('');
          setError(err instanceof Error ? err.message : 'Mermaid render failed');
        }
      }
    }

    void renderChart();
    return () => {
      cancelled = true;
    };
  }, [chart, renderId]);

  if (error) {
    return <pre className="my-4 overflow-x-auto rounded bg-muted p-4 text-[11px] text-foreground">{chart}</pre>;
  }

  return <div dangerouslySetInnerHTML={{ __html: svg }} className="my-4 flex justify-center overflow-x-auto rounded bg-white p-4 text-black" />;
}

function MarkdownRenderer({ content }: { content: string }) {
  const markdownComponents: Components = {
    code({ className, children, ...props }) {
      const match = /language-(\w+)/.exec(className || '');
      if (match?.[1] === 'mermaid') {
        return <Mermaid chart={String(children).replace(/\n$/, '')} />;
      }

      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
  };

  return (
    <div className="prose prose-sm max-w-none text-sm leading-7 text-muted-foreground prose-headings:text-foreground prose-strong:text-foreground prose-code:text-foreground prose-pre:bg-secondary/70 prose-blockquote:border-border prose-blockquote:text-muted-foreground">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  tone?: 'default' | 'number';
}) {
  return (
    <Card
      size="sm"
      className="h-full min-h-[108px] rounded-2xl border-border/60 bg-card/55 shadow-[0_10px_22px_rgba(0,0,0,0.1)]"
    >
      <CardContent className="flex h-full flex-col justify-between gap-3 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          {label}
        </p>
        {tone === 'number' ? (
          <p className="text-[28px] font-semibold leading-none tracking-tight text-foreground">
            {value}
          </p>
        ) : (
          <p className="overflow-hidden text-[13px] leading-5 text-foreground/85 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:3]">
            {value}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

const GLITCH_STYLES = `
  @keyframes reviewGlitch {
    0% { clip-path: inset(20% 0 80% 0); transform: translate(-2px, 1px); filter: hue-rotate(90deg); }
    20% { clip-path: inset(60% 0 10% 0); transform: translate(2px, -1px); filter: hue-rotate(-90deg); }
    40% { clip-path: inset(40% 0 50% 0); transform: translate(-2px, 2px); filter: invert(0.2); }
    60% { clip-path: inset(80% 0 5% 0); transform: translate(2px, -2px); filter: grayscale(1); }
    80% { clip-path: inset(10% 0 70% 0); transform: translate(-1px, 1px); filter: invert(0); }
    100% { clip-path: inset(0 0 0 0); transform: translate(0); filter: none; }
  }
  .animate-glitch {
    animation: reviewGlitch 0.35s cubic-bezier(0.25, 0.46, 0.45, 0.94) both;
  }
`;

function ReviewContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const explicitRunId = searchParams.get('run_id');

  const [review, setReview] = useState<ReviewData | null>(null);
  const [reviewer, setReviewer] = useState('Approver');
  const [comments, setComments] = useState<ReviewComment[]>([]);
  const [commentText, setCommentText] = useState('');
  const [commentSeverity, setCommentSeverity] = useState<ReviewSeverity>('medium');
  const [selectedAnchor, setSelectedAnchor] = useState<ReviewAnchor | null>(null);
  const [showDrawer, setShowDrawer] = useState(false);
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const [popoverPosition, setPopoverPosition] = useState<PopoverPosition | null>(null);
  const [highlightedAnchorKey, setHighlightedAnchorKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingComment, setSavingComment] = useState(false);
  const [submittingDecision, setSubmittingDecision] = useState<ReviewDecision | null>(null);
  const [isMobileComposer, setIsMobileComposer] = useState(false);

  const popoverRef = useRef<HTMLDivElement | null>(null);
  const composerResetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const paragraphRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const positionComposer = useCallback((triggerElement: HTMLElement) => {
    const rect = triggerElement.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 32);
    const sidebar = document.querySelector('aside');
    const sidebarRight = sidebar?.getBoundingClientRect().right ?? 0;
    const safeLeft = Math.max(16, sidebarRight + 16);
    let left = rect.left - width - 12;
    if (left < safeLeft) left = rect.right + 12;
    if (left + width > window.innerWidth - 16) {
      left = Math.max(safeLeft, window.innerWidth - width - 16);
    }
    if (left < safeLeft) left = safeLeft;

    let top = rect.top - 20;
    if (top < 88) top = 88;
    if (top + 300 > window.innerHeight - 16) {
      top = Math.max(88, window.innerHeight - 316);
    }

    setPopoverPosition({ left, top });
  }, []);

  const closeComposer = useCallback(() => {
    setSelectedAnchor(null);
    setPopoverPosition(null);
    setCommentText('');
    triggerRef.current = null;
  }, []);

  const load = useCallback(async () => {
    setLoading(true);

    try {
      let rfpIdToLoad = explicitRunId;
      if (!rfpIdToLoad) {
        const runs = await fetchRuns();
        const candidate = (runs.runs || []).find(
          (run: { status?: string; run_id?: string }) =>
            run.status === 'AWAITING_HUMAN_VALIDATION' || run.status === 'REVIEW_PENDING'
        );
        if (candidate?.run_id) rfpIdToLoad = candidate.run_id;
      }

      if (rfpIdToLoad) {
        const maxRetries = 5;
        const retryDelayMs = 1500;
        let loadedReview: ReviewData | null = null;

        for (let attempt = 0; attempt < maxRetries; attempt += 1) {
          try {
            loadedReview = await fetchReviewPackage(rfpIdToLoad);
            break;
          } catch (error) {
            if (attempt === maxRetries - 1) {
              console.error(error);
            } else {
              await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
            }
          }
        }

        if (loadedReview?.review_package) {
          setReview(loadedReview);
          setComments(loadedReview.review_package.comments || []);
          setReviewer(loadedReview.review_package.decision?.reviewer || 'Approver');
          setOpenSections((previous) => {
            const nextState: Record<string, boolean> = {};
            for (const section of loadedReview.review_package.response_sections || []) {
              nextState[section.section_id] = previous[section.section_id] ?? false;
            }
            return nextState;
          });
        }
      }
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, [explicitRunId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const syncViewport = () => setIsMobileComposer(window.innerWidth < 768);
    syncViewport();
    window.addEventListener('resize', syncViewport);
    return () => window.removeEventListener('resize', syncViewport);
  }, []);

  useEffect(() => {
    if (!selectedAnchor || isMobileComposer || !triggerRef.current) return;

    positionComposer(triggerRef.current);
    const handleViewportChange = () => {
      if (triggerRef.current) positionComposer(triggerRef.current);
    };

    window.addEventListener('scroll', handleViewportChange, true);
    window.addEventListener('resize', handleViewportChange);

    return () => {
      window.removeEventListener('scroll', handleViewportChange, true);
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [isMobileComposer, positionComposer, selectedAnchor]);

  useEffect(() => {
    if (!selectedAnchor) return;
    const timer = window.setTimeout(() => {
      const textarea = popoverRef.current?.querySelector('textarea');
      textarea?.focus();
    }, 80);
    return () => window.clearTimeout(timer);
  }, [selectedAnchor]);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!selectedAnchor) return;
      const target = event.target as HTMLElement | null;
      if (!target) return;
      if (popoverRef.current?.contains(target)) return;
      if (target.closest('[data-comment-trigger="true"]')) return;
      closeComposer();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (selectedAnchor) closeComposer();
        else if (showDrawer) setShowDrawer(false);
      }
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [closeComposer, selectedAnchor, showDrawer]);

  useEffect(() => {
    setComments(review?.review_package?.comments || []);
  }, [review]);

  useEffect(() => {
    return () => {
      if (composerResetTimer.current) clearTimeout(composerResetTimer.current);
    };
  }, []);

  const rp = review?.review_package;
  const runStatus = normalizeReviewStatus(review?.status || '');
  const packageStatus = normalizeReviewStatus(rp?.status || '');
  const canAct =
    runStatus === 'AWAITING_HUMAN_VALIDATION' ||
    (!runStatus && packageStatus === 'PENDING') ||
    packageStatus === 'PENDING';

  const responseSections = rp?.response_sections || [];
  const summaryCards = [
    { label: 'Review Status', value: humanizeStatus(rp?.status), tone: 'default' as const },
    { label: 'Response Sections', value: responseSections.length, tone: 'number' as const },
    { label: 'Open Comments', value: comments.length, tone: 'number' as const },
    {
      label: 'Validation',
      value: rp?.validation_summary || 'No validation summary was generated.',
      tone: 'default' as const,
    },
    {
      label: 'Commercial',
      value: rp?.commercial_summary || 'No commercial summary was generated.',
      tone: 'default' as const,
    },
    {
      label: 'Legal',
      value: rp?.legal_summary || 'No legal summary was generated.',
      tone: 'default' as const,
    },
  ];

  const getSectionCommentCount = (sectionId: string) =>
    comments.filter((comment) => comment.anchor?.section_id === sectionId).length;

  const getParagraphCommentCount = (sectionId: string, paragraphId: string) =>
    comments.filter(
      (comment) =>
        comment.anchor?.section_id === sectionId &&
        (comment.anchor?.paragraph_id || '') === paragraphId
    ).length;

  const toggleSection = (sectionId: string) => {
    setOpenSections((previous) => ({
      ...previous,
      [sectionId]: !previous[sectionId],
    }));
  };

  const openCommentComposer = (
    section: ReviewSection,
    triggerElement: HTMLElement,
    paragraph?: ReviewParagraph
  ) => {
    const nextAnchor = buildAnchor(section, paragraph);
    triggerRef.current = triggerElement;
    setSelectedAnchor(nextAnchor);
    setCommentText('');
    setCommentSeverity('medium');
    setOpenSections((previous) => ({
      ...previous,
      [section.section_id]: true,
    }));

    if (!isMobileComposer) positionComposer(triggerElement);
  };

  const jumpToAnchor = (anchor: ReviewAnchor) => {
    const key = anchorKey(anchor);
    setOpenSections((previous) => ({
      ...previous,
      [anchor.section_id]: true,
    }));
    setShowDrawer(false);

    window.requestAnimationFrame(() => {
      paragraphRefs.current[key]?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
      setHighlightedAnchorKey(key);
      if (composerResetTimer.current) clearTimeout(composerResetTimer.current);
      composerResetTimer.current = setTimeout(() => setHighlightedAnchorKey(null), 1800);
    });
  };

  const addComment = async () => {
    if (!review || !selectedAnchor || !commentText.trim()) return;

    const nextComments: ReviewComment[] = [
      ...comments,
      {
        comment_id: `REV-CMT-${Date.now()}`,
        anchor: selectedAnchor,
        comment: commentText.trim(),
        severity: commentSeverity,
        author: reviewer.trim() || 'Anonymous',
        created_at: new Date().toISOString(),
      },
    ];

    setSavingComment(true);
    try {
      const response = await saveReviewComments(review.rfp_id, nextComments);
      setReview(response);
      setComments(response.review_package?.comments || nextComments);
      setShowDrawer(true);
      closeComposer();
    } catch (error) {
      console.error(error);
    } finally {
      setSavingComment(false);
    }
  };

  const removeComment = async (commentId: string) => {
    if (!review) return;

    const previousComments = comments;
    const nextComments = comments.filter((comment) => comment.comment_id !== commentId);
    setComments(nextComments);

    try {
      const response = await saveReviewComments(review.rfp_id, nextComments);
      setReview(response);
      setComments(response.review_package?.comments || nextComments);
    } catch (error) {
      console.error(error);
      setComments(previousComments);
    }
  };

  const handleDecision = async (decision: ReviewDecision) => {
    if (!review || !canAct) return;
    if (decision === 'REQUEST_CHANGES' && comments.length === 0) return;

    setSubmittingDecision(decision);
    try {
      await submitReviewDecision(review.rfp_id, {
        decision,
        reviewer: reviewer.trim() || 'Anonymous',
        summary: `Reviewed via Next.js (${comments.length} comment${comments.length === 1 ? '' : 's'})`,
        rerun_from: 'auto',
        comments,
      });
      router.push(`/?run_id=${review.rfp_id}`);
    } catch (error) {
      console.error(error);
    } finally {
      setSubmittingDecision(null);
    }
  };

  if (loading) {
    return (
      <>
        <Topbar title="Review Workspace" />\n      <style dangerouslySetInnerHTML={{ __html: GLITCH_STYLES }} />
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Loading review workspace...
        </div>
      </>
    );
  }

  if (!review || !rp) {
    return (
      <>
        <Topbar title="Review Workspace" />\n      <style dangerouslySetInnerHTML={{ __html: GLITCH_STYLES }} />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted-foreground">
          <FileSearch className="h-12 w-12 opacity-20" />
          <p>No proposal is currently available for human review.</p>
          <p className="text-xs">Wait for a run to reach the Human Validation stage.</p>
        </div>
      </>
    );
  }

  return (
    <>
      <Topbar title="Review Workspace" />
      <style dangerouslySetInnerHTML={{ __html: GLITCH_STYLES }} />\n      <style dangerouslySetInnerHTML={{ __html: GLITCH_STYLES }} />

      <div className="border-b border-border/70 bg-background/95">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                  Human Review
                </p>
                <Badge variant="outline" className={cn('text-[10px] uppercase', statusBadgeClass(rp.status))}>
                  {humanizeStatus(rp.status)}
                </Badge>
              </div>
              <h1 className="text-lg font-semibold text-foreground sm:text-xl">
                Proposal {review.rfp_id}
              </h1>
              <p className="text-xs text-muted-foreground">
                Expand a section, hover a paragraph, and use the plus action to leave anchored feedback.
              </p>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-end">
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                <span className="text-[10px] font-semibold uppercase tracking-[0.18em]">Reviewer</span>
                <Input
                  value={reviewer}
                  onChange={(event) => setReviewer(event.target.value)}
                  placeholder="Your name"
                  className="h-9 w-full rounded-xl border-border bg-secondary/70 text-sm sm:w-48"
                />
              </label>

              <div className="flex items-center gap-3 rounded-2xl border border-border/60 bg-card/55 px-3 py-2 text-xs text-muted-foreground">
                <span>{responseSections.length} sections</span>
                <span className="h-1 w-1 rounded-full bg-border" />
                <span>{comments.length} comments</span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {summaryCards.map((item) => (
              <SummaryCard
                key={item.label}
                label={item.label}
                value={item.value}
                tone={item.tone}
              />
            ))}
          </div>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-5 px-4 py-6 pb-32 sm:px-6 lg:px-8">
          <div className="space-y-1">
            <p className="text-sm font-semibold text-foreground">Response Sections</p>
            <p className="text-xs text-muted-foreground">
              Click a section to read the full C2 output. Hover paragraphs to add anchored comments, or use the section plus button for whole-section feedback.
            </p>
          </div>

          <div className="space-y-4">
            {responseSections.length === 0 ? (
              <Card className="rounded-2xl border-dashed border-border/80 bg-card/35">
                <CardContent className="py-10 text-center text-sm text-muted-foreground">
                  No response sections were provided in the review package.
                </CardContent>
              </Card>
            ) : (
              responseSections.map((section) => {
                const sectionCommentCount = getSectionCommentCount(section.section_id);
                const paragraphCount = section.paragraphs?.length || (section.full_text ? 1 : 0);
                const isOpen = openSections[section.section_id] ?? false;

                return (
                  <Card
                    key={section.section_id}
                    className="overflow-hidden rounded-2xl border-border/60 bg-card/50 shadow-[0_14px_28px_rgba(0,0,0,0.1)]"
                  >
                    <div
                      role="button"
                      tabIndex={0}
                      className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-secondary/[0.12]"
                      onClick={() => toggleSection(section.section_id)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          toggleSection(section.section_id);
                        }
                      }}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="truncate text-sm font-semibold text-foreground">
                            {section.title || section.section_id}
                          </p>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                          <span>{section.section_id}</span>
                          <span className="h-1 w-1 rounded-full bg-border" />
                          <span>
                            {paragraphCount} para{paragraphCount === 1 ? '' : 's'}
                          </span>
                          {sectionCommentCount > 0 && (
                            <>
                              <span className="h-1 w-1 rounded-full bg-border" />
                              <span>{sectionCommentCount} comments</span>
                            </>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-3 text-muted-foreground">
                        {sectionCommentCount > 0 && (
                          <span className="inline-flex items-center gap-1 text-[11px]">
                            <MessageSquare className="h-3.5 w-3.5" />
                            {sectionCommentCount}
                          </span>
                        )}
                        <span className="rounded-lg border border-border/60 bg-secondary/40 p-2">
                          <ChevronDown
                            className={cn(
                              'h-4 w-4 transition-transform duration-200',
                              isOpen ? 'rotate-0' : '-rotate-90'
                            )}
                          />
                        </span>
                      </div>
                    </div>

                    {isOpen && (
                      <div className="border-t border-border/60 bg-secondary/[0.14] px-5 py-4 animate-glitch">
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                          <div className="text-[11px] text-muted-foreground">
                            Scroll the full section below and use the plus controls for paragraph or section comments.
                          </div>
                          {sectionCommentCount > 0 && (
                            <span className="rounded-full border border-amber-400/20 bg-amber-500/[0.08] px-2.5 py-1 text-[11px] text-amber-300">
                              {sectionCommentCount} anchored comment
                              {sectionCommentCount === 1 ? '' : 's'}
                            </span>
                          )}
                        </div>

                        <div className="rounded-2xl border border-border/60 bg-background/55 p-3">
                          <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-border/50 bg-card/55 px-3 py-2.5">
                            <div>
                              <p className="text-sm font-medium text-foreground">Section overview</p>
                              <p className="text-[11px] text-muted-foreground">
                                Add feedback for the full section or drill into individual paragraphs below.
                              </p>
                            </div>
                            <Button
                              data-comment-trigger="true"
                              variant="outline"
                              size="sm"
                              className="rounded-xl"
                              onClick={(event) => openCommentComposer(section, event.currentTarget)}
                              aria-label="Comment on whole section"
                            >
                              <Plus className="mr-1.5 h-4 w-4" />
                              Comment on section
                            </Button>
                          </div>

                          <div className="max-h-[56vh] space-y-3 overflow-y-auto pr-1">
                            {section.paragraphs?.length > 0 ? (
                              section.paragraphs.map((paragraph, index) => {
                                const anchor = buildAnchor(section, paragraph);
                                const key = anchorKey(anchor);
                                const paragraphCommentCount = getParagraphCommentCount(
                                  section.section_id,
                                  paragraph.paragraph_id
                                );
                                const isSelected = selectedAnchor ? anchorKey(selectedAnchor) === key : false;
                                const isHighlighted = highlightedAnchorKey === key;

                                return (
                                  <div
                                    key={paragraph.paragraph_id}
                                    ref={(node) => {
                                      paragraphRefs.current[key] = node;
                                    }}
                                    className={cn(
                                      'group/paragraph relative rounded-xl border border-transparent bg-background/65 px-4 py-4 pl-12 transition-all duration-200',
                                      'hover:border-border/70 hover:bg-background/85',
                                      paragraphCommentCount > 0 &&
                                      'border-amber-400/20 bg-amber-500/[0.05]',
                                      (isSelected || isHighlighted) &&
                                      'border-sky-400/35 bg-sky-500/[0.08] shadow-[0_0_0_1px_rgba(56,189,248,0.18)]'
                                    )}
                                  >
                                    <Button
                                      data-comment-trigger="true"
                                      variant="ghost"
                                      size="icon-sm"
                                      className={cn(
                                        'absolute left-3 top-3 rounded-lg border border-border/60 bg-card/90 text-muted-foreground shadow-sm',
                                        'opacity-0 transition duration-200 group-hover/paragraph:opacity-100 focus-visible:opacity-100',
                                        paragraphCommentCount > 0 &&
                                        'opacity-100 text-amber-300 hover:text-amber-200'
                                      )}
                                      onClick={(event) =>
                                        openCommentComposer(section, event.currentTarget, paragraph)
                                      }
                                      aria-label="Add paragraph feedback"
                                    >
                                      <Plus className="h-4 w-4" />
                                    </Button>

                                    {paragraphCommentCount > 0 && (
                                      <button
                                        type="button"
                                        className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full border border-amber-400/20 bg-amber-500/[0.08] px-2.5 py-1 text-[10px] font-medium text-amber-300 transition hover:bg-amber-500/[0.14]"
                                        onClick={() => setShowDrawer(true)}
                                        title="View comments"
                                      >
                                        <MessageSquare className="h-3 w-3" />
                                        {paragraphCommentCount}
                                      </button>
                                    )}

                                    <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                                      <span>{formatParagraphLabel(paragraph.paragraph_id, index)}</span>
                                    </div>

                                    <MarkdownRenderer content={paragraph.text} />
                                  </div>
                                );
                              })
                            ) : (
                              <div
                                ref={(node) => {
                                  paragraphRefs.current[anchorKey(buildAnchor(section))] = node;
                                }}
                                className={cn(
                                  'group/paragraph relative rounded-xl border bg-background/65 px-4 py-4 pl-12 transition-all duration-200',
                                  'border-transparent hover:border-border/70 hover:bg-background/85',
                                  getSectionCommentCount(section.section_id) > 0 &&
                                  'border-amber-400/20 bg-amber-500/[0.05]'
                                )}
                              >
                                <Button
                                  data-comment-trigger="true"
                                  variant="ghost"
                                  size="icon-sm"
                                  className={cn(
                                    'absolute left-3 top-3 rounded-lg border border-border/60 bg-card/90 text-muted-foreground shadow-sm',
                                    'opacity-0 transition duration-200 group-hover/paragraph:opacity-100 focus-visible:opacity-100',
                                    getSectionCommentCount(section.section_id) > 0 &&
                                    'opacity-100 text-amber-300 hover:text-amber-200'
                                  )}
                                  onClick={(event) => openCommentComposer(section, event.currentTarget)}
                                  aria-label="Add section feedback"
                                >
                                  <Plus className="h-4 w-4" />
                                </Button>

                                {getSectionCommentCount(section.section_id) > 0 && (
                                  <button
                                    type="button"
                                    className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full border border-amber-400/20 bg-amber-500/[0.08] px-2.5 py-1 text-[10px] font-medium text-amber-300 transition hover:bg-amber-500/[0.14]"
                                    onClick={() => setShowDrawer(true)}
                                  >
                                    <MessageSquare className="h-3 w-3" />
                                    {getSectionCommentCount(section.section_id)}
                                  </button>
                                )}

                                <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                                  Section note
                                </div>
                                <MarkdownRenderer content={section.full_text || 'No content provided.'} />
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </Card>
                );
              })
            )}
          </div>
        </div>
      </ScrollArea>

      {selectedAnchor && (isMobileComposer || popoverPosition) && (
        <div
          ref={popoverRef}
          className={cn(
            'fixed z-[200]',
            isMobileComposer ? 'inset-x-4 bottom-24' : ''
          )}
          style={!isMobileComposer && popoverPosition
            ? {
              left: popoverPosition.left,
              top: popoverPosition.top,
              width: Math.min(360, typeof window !== 'undefined' ? window.innerWidth - 32 : 360),
            }
            : undefined}
        >
          <Card className="rounded-2xl border-border/70 bg-background/97 shadow-[0_22px_60px_rgba(0,0,0,0.22)] backdrop-blur-xl">
            <CardHeader className="border-b border-border/60 pb-4">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <CardTitle className="text-sm">Add Feedback</CardTitle>
                  <p className="text-xs text-muted-foreground">{formatAnchorLabel(selectedAnchor)}</p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="rounded-xl"
                  onClick={closeComposer}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>

            <CardContent className="space-y-3 py-4">
              <div className="rounded-xl border border-dashed border-border/60 bg-secondary/35 px-3 py-2.5 text-xs text-muted-foreground">
                <p className="mb-1 font-medium text-foreground">
                  {selectedAnchor.section_title}
                  {selectedAnchor.paragraph_id ? ` / ${formatParagraphLabel(selectedAnchor.paragraph_id, 0)}` : ''}
                </p>
                <p className="leading-5">&quot;{selectedAnchor.excerpt}&quot;</p>
              </div>

              <Textarea
                value={commentText}
                onChange={(event) => setCommentText(event.target.value)}
                rows={4}
                placeholder="Describe what should change and why..."
                className="rounded-xl border-border bg-secondary/45 text-sm"
              />

              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <select
                  value={commentSeverity}
                  onChange={(event) => setCommentSeverity(event.target.value as ReviewSeverity)}
                  className="h-9 rounded-xl border border-border bg-secondary/45 px-3 text-sm text-foreground outline-none transition focus:border-ring"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>

                <Button
                  size="sm"
                  className="rounded-xl sm:ml-auto"
                  disabled={!commentText.trim() || savingComment}
                  onClick={addComment}
                >
                  {savingComment ? 'Saving...' : 'Save Comment'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {showDrawer && (
        <>
          <button
            type="button"
            aria-label="Close comments drawer"
            className="fixed inset-0 z-[170] bg-black/30 backdrop-blur-[2px]"
            onClick={() => setShowDrawer(false)}
          />

          <div className="fixed right-0 top-0 z-[180] flex h-full w-full max-w-[420px] flex-col border-l border-border/70 bg-background/97 shadow-[-14px_0_40px_rgba(0,0,0,0.24)] backdrop-blur-xl">
            <div className="flex items-center justify-between border-b border-border/70 px-5 py-4">
              <div>
                <p className="text-sm font-semibold text-foreground">Comments & Feedback</p>
                <p className="text-xs text-muted-foreground">
                  {comments.length === 0
                    ? 'No comments have been added yet.'
                    : `${comments.length} anchored comment${comments.length === 1 ? '' : 's'}`}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                className="rounded-xl"
                onClick={() => setShowDrawer(false)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <ScrollArea className="flex-1">
              <div className="space-y-3 px-5 py-4">
                {comments.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-border/70 bg-card/35 px-4 py-10 text-center text-sm text-muted-foreground">
                    Add feedback from the paragraph plus button and it will appear here.
                  </div>
                ) : (
                  comments.map((comment) => (
                    <Card key={comment.comment_id} className="rounded-2xl border-border/60 bg-card/55">
                      <CardContent className="space-y-3 py-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-foreground">
                              {formatAnchorLabel(comment.anchor)}
                            </p>
                            <p className="mt-1 text-[11px] text-muted-foreground">
                              {comment.author || 'Reviewer'}
                              {comment.created_at
                                ? ` | ${new Date(comment.created_at).toLocaleString()}`
                                : ''}
                            </p>
                          </div>
                          <Badge
                            variant="outline"
                            className={cn('text-[10px] uppercase', severityBadgeClass(comment.severity))}
                          >
                            {comment.severity}
                          </Badge>
                        </div>

                        <div className="rounded-xl border border-border/60 bg-secondary/45 px-3 py-2 text-xs leading-5 text-muted-foreground">
                          &quot;{comment.anchor?.excerpt || 'No excerpt available.'}&quot;
                        </div>

                        <p className="text-sm leading-6 text-foreground">{comment.comment}</p>

                        <div className="flex items-center justify-between gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="rounded-xl"
                            onClick={() => jumpToAnchor(comment.anchor)}
                          >
                            <Crosshair className="mr-1.5 h-4 w-4" />
                            Jump to anchor
                          </Button>

                          <Button
                            variant="ghost"
                            size="sm"
                            className="rounded-xl text-rose-300 hover:bg-rose-500/10 hover:text-rose-200"
                            onClick={() => removeComment(comment.comment_id)}
                          >
                            <Trash2 className="mr-1.5 h-4 w-4" />
                            Remove
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
        </>
      )}

      <div className="fixed bottom-4 left-1/2 z-[160] w-[calc(100%-1.5rem)] max-w-fit -translate-x-1/2 rounded-[22px] border border-border/70 bg-card/94 px-3 py-3 shadow-[0_20px_50px_rgba(0,0,0,0.2)] backdrop-blur-xl">
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="rounded-xl"
            onClick={() => setShowDrawer((previous) => !previous)}
          >
            <MessageSquare className="mr-1.5 h-4 w-4" />
            {showDrawer ? 'Hide comments' : `Show comments (${comments.length})`}
          </Button>
          <Separator orientation="vertical" className="hidden h-7 lg:block" />
          <Button
            variant="outline"
            size="sm"
            className="rounded-xl border-rose-400/20 text-rose-300 hover:bg-rose-500/10 hover:text-rose-200"
            disabled={!canAct || Boolean(submittingDecision)}
            onClick={() => handleDecision('REJECT')}
          >
            {submittingDecision === 'REJECT' ? 'Rejecting...' : 'Reject'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="rounded-xl border-amber-400/20 text-amber-300 hover:bg-amber-500/10 hover:text-amber-200"
            disabled={!canAct || comments.length === 0 || Boolean(submittingDecision)}
            onClick={() => handleDecision('REQUEST_CHANGES')}
          >
            {submittingDecision === 'REQUEST_CHANGES'
              ? 'Submitting...'
              : 'Request Changes'}
          </Button>
          <Button
            size="sm"
            className="rounded-xl bg-emerald-500 text-emerald-950 hover:bg-emerald-400"
            disabled={!canAct || Boolean(submittingDecision)}
            onClick={() => handleDecision('APPROVE')}
          >
            <Check className="mr-1.5 h-4 w-4" />
            {submittingDecision === 'APPROVE' ? 'Approving...' : 'Approve & Submit'}
          </Button>
        </div>
      </div>
    </>
  );
}

export default function ReviewPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading...</div>}>
      <ReviewContent />
    </Suspense>
  );
}
