import { ReactNode, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

type RecordLike = Record<string, any>;

function formatNumber(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString();
  if (typeof value === 'string') return value;
  if (value == null) return '-';
  return String(value);
}

function StatCard({ label, value, tone = 'default' }: { label: string; value: ReactNode; tone?: 'default' | 'success' | 'warning' | 'danger' | 'accent' }) {
  const toneClass = {
    default: 'border-border text-foreground',
    success: 'border-success/30 text-success',
    warning: 'border-warning/30 text-warning',
    danger: 'border-error/30 text-error',
    accent: 'border-primary/30 text-primary',
  }[tone];

  return (
    <div className={`rounded-lg border bg-secondary/30 px-4 py-3 min-w-[120px] ${toneClass}`}>
      <div className="text-lg font-semibold leading-none">{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
    </div>
  );
}

function Chip({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'success' | 'warning' | 'danger' | 'accent' }) {
  const toneClass = {
    default: 'bg-secondary text-foreground',
    success: 'bg-success/15 text-success',
    warning: 'bg-warning/15 text-warning',
    danger: 'bg-error/15 text-error',
    accent: 'bg-primary/15 text-primary',
  }[tone];

  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${toneClass}`}>{children}</span>;
}

function OutputAccordion({ title, children, defaultOpen = false }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-border rounded-lg bg-card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-3 text-sm font-semibold hover:bg-secondary/50 transition-colors"
      >
        <span>{title}</span>
        {open ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
      </button>
      {open && <div className="p-4 border-t border-border bg-card/50 space-y-4">{children}</div>}
    </div>
  );
}

function JsonFallback({ value }: { value: unknown }) {
  return <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap break-all">{JSON.stringify(value, null, 2)}</pre>;
}

function SimpleTable({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto border border-border rounded-md">
      <table className="w-full text-xs text-left">
        <thead className="bg-secondary border-b border-border">
          <tr>
            {headers.map((header) => <th key={header} className="p-2 font-semibold">{header}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row, index) => (
            <tr key={index} className="align-top hover:bg-muted/10">
              {row.map((cell, cellIndex) => <td key={cellIndex} className="p-2">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderB2(output: RecordLike) {
  const confidence = Number(output.confidence_score || 0);
  const issues = Array.isArray(output.issues) ? output.issues : [];
  const requirements = Array.isArray(output.validated_requirements) ? output.validated_requirements : [];
  return (
    <OutputAccordion title={`B2 Requirements Validation - ${(confidence * 100).toFixed(0)}% confidence`}>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Confidence" value={`${(confidence * 100).toFixed(0)}%`} tone={confidence >= 0.8 ? 'success' : confidence >= 0.6 ? 'warning' : 'danger'} />
        <StatCard label="Total" value={formatNumber(output.total_requirements || requirements.length)} />
        <StatCard label="Duplicates" value={formatNumber(output.duplicate_count || 0)} tone={(output.duplicate_count || 0) > 0 ? 'warning' : 'success'} />
        <StatCard label="Contradictions" value={formatNumber(output.contradiction_count || 0)} tone={(output.contradiction_count || 0) > 0 ? 'danger' : 'success'} />
      </div>
      {issues.length > 0 ? (
        <div className="space-y-2">
          <div className="text-xs font-semibold">Identified issues</div>
          {issues.map((issue: any, index: number) => (
            <div key={index} className="rounded-lg border border-border bg-secondary/40 p-3 text-xs space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={issue.severity === 'error' ? 'danger' : issue.severity === 'warning' ? 'warning' : 'accent'}>{issue.issue_type || 'Issue'}</Chip>
                <Chip tone={issue.severity === 'error' ? 'danger' : issue.severity === 'warning' ? 'warning' : 'default'}>{issue.severity || 'warning'}</Chip>
                {(issue.requirement_ids || []).map((requirementId: string) => <Chip key={requirementId} tone="accent">{requirementId}</Chip>)}
              </div>
              <div className="text-muted-foreground">{issue.description || 'No description provided.'}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-success/20 bg-success/10 px-3 py-2 text-xs text-success">No requirement validation issues were identified.</div>
      )}
      {requirements.length > 0 && (
        <SimpleTable
          headers={['ID', 'Type', 'Class', 'Requirement']}
          rows={requirements.map((requirement: any) => [
            <span className="font-semibold text-primary" key="id">{requirement.requirement_id}</span>,
            <Chip key="type" tone={requirement.type === 'MANDATORY' ? 'danger' : 'accent'}>{requirement.type || '-'}</Chip>,
            <Chip key="class">{requirement.classification || '-'}</Chip>,
            <span key="text" className="max-w-xl block">{requirement.text || '-'}</span>,
          ])}
        />
      )}
    </OutputAccordion>
  );
}

function renderC1(output: RecordLike) {
  const sections = Array.isArray(output.sections) ? output.sections : [];
  const gaps = Array.isArray(output.coverage_gaps) ? output.coverage_gaps : [];
  return (
    <OutputAccordion title={`C1 Architecture Planning (${sections.length} sections${gaps.length ? `, ${gaps.length} gaps` : ''})`}>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Sections" value={formatNumber(output.total_sections || sections.length)} />
        <StatCard label="Coverage Gaps" value={gaps.length} tone={gaps.length ? 'danger' : 'success'} />
      </div>
      {output.rfp_response_instructions && (
        <div className="rounded-lg border border-primary/20 bg-primary/10 px-3 py-2 text-xs text-foreground">
          <div className="font-semibold text-primary mb-1">RFP response instructions</div>
          <div className="text-muted-foreground">{output.rfp_response_instructions}</div>
        </div>
      )}
      {sections.length > 0 && (
        <SimpleTable
          headers={['Section', 'Title', 'Type', 'Priority', 'Description', 'Content Guidance', 'Requirements', 'Capabilities', 'Source RFP Section']}
          rows={sections.map((section: any) => [
            <span className="font-semibold text-primary" key="id">{section.section_id}</span>,
            section.title || '-',
            <Chip key="type" tone={section.section_type === 'legal' ? 'warning' : section.section_type === 'commercial' ? 'accent' : section.section_type === 'knowledge_driven' ? 'success' : 'default'}>{section.section_type || '-'}</Chip>,
            section.priority || '-',
            <span key="desc" className="max-w-xs block">{section.description || '-'}</span>,
            <span key="guide" className="max-w-xs block text-muted-foreground">{section.content_guidance || '-'}</span>,
            <div key="reqs" className="flex flex-wrap gap-1">{(section.requirement_ids || []).length ? (section.requirement_ids || []).map((id: string) => <Chip key={id} tone="accent">{id}</Chip>) : '-'}</div>,
            <span key="caps" className="max-w-[180px] block">{(section.mapped_capabilities || []).join(', ') || '-'}</span>,
            section.source_rfp_section || '-',
          ])}
        />
      )}
      {gaps.length > 0 && <div className="rounded-lg border border-error/20 bg-error/10 px-3 py-2 text-xs text-error">Coverage gaps: {gaps.join(', ')}</div>}
    </OutputAccordion>
  );
}

function renderC2(output: RecordLike) {
  const sections = Array.isArray(output.section_responses) ? output.section_responses : [];
  const coverage = Array.isArray(output.coverage_matrix) ? output.coverage_matrix : [];
  const totalWords = sections.reduce((sum: number, section: any) => sum + Number(section.word_count || 0), 0);
  const coveredRequirements = new Set(sections.flatMap((section: any) => section.requirements_addressed || [])).size;
  return (
    <OutputAccordion title={`C2 Requirement Writing (${sections.length} sections, ${totalWords.toLocaleString()} words)`}>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Sections" value={sections.length} />
        <StatCard label="Total Words" value={totalWords.toLocaleString()} />
        <StatCard label="Reqs Covered" value={coveredRequirements} tone="accent" />
      </div>
      {sections.length > 0 && (
        <div className="space-y-2">
          {sections.map((section: any, index: number) => (
            <details key={index} className="rounded-lg border border-border bg-secondary/30">
              <summary className="cursor-pointer list-none px-4 py-3 flex items-center justify-between gap-3 text-xs">
                <div>
                  <span className="font-semibold text-primary mr-2">{section.section_id}</span>
                  <span className="font-medium text-foreground">{section.title}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <span>{section.word_count || 0} words</span>
                  {(section.requirements_addressed || []).length > 0 && <Chip tone="accent">{section.requirements_addressed.length} reqs</Chip>}
                </div>
              </summary>
              <div className="px-4 pb-4 space-y-3 text-xs">
                {(section.requirements_addressed || []).length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {(section.requirements_addressed || []).map((requirementId: string) => <Chip key={requirementId} tone="accent">{requirementId}</Chip>)}
                  </div>
                )}
                <div className="text-muted-foreground whitespace-pre-wrap leading-6">{section.content || '-'}</div>
              </div>
            </details>
          ))}
        </div>
      )}
      {coverage.length > 0 && (
        <SimpleTable
          headers={['Requirement', 'Section', 'Coverage']}
          rows={coverage.map((item: any) => [
            <span key="req" className="font-semibold text-primary">{item.requirement_id}</span>,
            item.addressed_in_section || '-',
            <Chip key="coverage" tone={item.coverage_quality === 'full' ? 'success' : item.coverage_quality === 'partial' ? 'warning' : 'danger'}>{item.coverage_quality || '-'}</Chip>,
          ])}
        />
      )}
    </OutputAccordion>
  );
}

function renderC3(output: RecordLike) {
  const coverageAppendix = output.coverage_appendix || '';
  const coverageMatch = coverageAppendix.match(/\*\*Coverage Summary:\*\*\s*(.+)/);
  const coverageLine = coverageMatch?.[1]?.trim() || '';
  const executiveSummary = output.executive_summary || '';
  const preview = executiveSummary.length > 500 ? `${executiveSummary.slice(0, 500).trimEnd()}...` : executiveSummary;
  const sectionOrder = Array.isArray(output.section_order) ? output.section_order : [];

  return (
    <OutputAccordion title="C3 Narrative Assembly" defaultOpen>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Total Words" value={formatNumber(output.word_count || 0)} />
        <StatCard label="Sections" value={formatNumber(output.sections_included || sectionOrder.length)} tone="accent" />
        <StatCard label="Placeholders" value={output.has_placeholders ? 'Yes' : 'No'} tone={output.has_placeholders ? 'warning' : 'success'} />
      </div>
      {coverageLine && <div className="rounded-lg border border-primary/20 bg-primary/10 px-3 py-2 text-xs text-foreground"><span className="font-semibold text-primary">Coverage:</span> <span className="text-muted-foreground">{coverageLine}</span></div>}
      {preview && (
        <div className="space-y-2">
          <div className="text-xs font-semibold">Executive summary</div>
          <div className="rounded-lg border border-border bg-secondary/30 px-3 py-3 text-xs text-muted-foreground whitespace-pre-wrap leading-6">{preview}</div>
        </div>
      )}
      {sectionOrder.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-semibold">Section order</div>
          <div className="flex flex-wrap gap-1.5">
            {sectionOrder.map((section: string, index: number) => <Chip key={`${section}-${index}`} tone="accent">{index + 1}. {section}</Chip>)}
          </div>
        </div>
      )}
    </OutputAccordion>
  );
}

function renderD1(output: RecordLike) {
  const decision = String(output.decision || 'PASS').toUpperCase();
  const checks = Array.isArray(output.checks) ? output.checks : [];
  const hasAutoPass = checks.some((check: any) => String(check.description || '').toLowerCase().includes('auto-pass'));
  return (
    <OutputAccordion title="D1 Technical Validation" defaultOpen>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Decision" value={decision} tone={decision === 'PASS' ? 'success' : 'danger'} />
        <StatCard label="Critical" value={formatNumber(output.critical_failures || 0)} tone={(output.critical_failures || 0) > 0 ? 'danger' : 'success'} />
        <StatCard label="Warnings" value={formatNumber(output.warnings || 0)} tone={(output.warnings || 0) > 0 ? 'warning' : 'success'} />
        <StatCard label="Retries" value={formatNumber(output.retry_count || 0)} tone={(output.retry_count || 0) > 0 ? 'accent' : 'success'} />
      </div>
      {hasAutoPass && <div className="rounded-lg border border-warning/20 bg-warning/10 px-3 py-2 text-xs text-warning">Some checks were auto-passed because the validation response could not be parsed cleanly.</div>}
      {checks.length > 0 && (
        <SimpleTable
          headers={['Check', 'Status', 'Description', 'Issues']}
          rows={checks.map((check: any) => {
            const issues = Array.isArray(check.issues) ? check.issues : [];
            const autoPassed = String(check.description || '').toLowerCase().includes('auto-pass');
            return [
              <span key="name" className="font-semibold capitalize">{check.check_name || '-'}</span>,
              <Chip key="status" tone={check.passed ? (autoPassed ? 'warning' : 'success') : 'danger'}>{check.passed ? (autoPassed ? 'AUTO-PASS' : 'PASS') : 'FAIL'}</Chip>,
              <span key="description" className="text-muted-foreground">{check.description || '-'}</span>,
              <div key="issues" className="space-y-1 text-muted-foreground">{issues.length ? issues.map((issue: string, index: number) => <div key={index}>- {issue}</div>) : '-'}</div>,
            ];
          })}
        />
      )}
      {output.feedback_for_revision && (
        <div className="rounded-lg border border-error/20 bg-error/10 px-3 py-3 text-xs text-muted-foreground whitespace-pre-wrap">
          <div className="font-semibold text-error mb-1">Feedback for revision</div>
          {output.feedback_for_revision}
        </div>
      )}
    </OutputAccordion>
  );
}

function renderE1(output: RecordLike) {
  const items = Array.isArray(output.line_items) ? output.line_items : [];
  return (
    <OutputAccordion title="E1 Commercial Review" defaultOpen>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Decision" value={String(output.decision || 'APPROVED').toUpperCase()} tone={String(output.decision || 'APPROVED').toUpperCase() === 'APPROVED' ? 'success' : 'warning'} />
        <StatCard label="Total Price" value={`${output.currency || 'USD'} ${formatNumber(output.total_price || 0)}`} tone="accent" />
        <StatCard label="Confidence" value={`${Math.round(Number(output.confidence || 0) * 100)}%`} />
      </div>
      {(output.validation_flags || []).length > 0 && (
        <div className="rounded-lg border border-warning/20 bg-warning/10 px-3 py-2 text-xs text-muted-foreground">
          <div className="font-semibold text-warning mb-1">Validation flags</div>
          <div className="space-y-1">{(output.validation_flags || []).map((flag: string, index: number) => <div key={index}>- {flag}</div>)}</div>
        </div>
      )}
      {items.length > 0 && (
        <SimpleTable
          headers={['Category', 'Label', 'Total']}
          rows={items.map((item: any) => [
            <Chip key="category" tone="accent">{item.category || '-'}</Chip>,
            <span key="label" className="text-muted-foreground">{item.label || '-'}</span>,
            <span key="total" className="font-semibold">{output.currency || 'USD'} {formatNumber(item.total || 0)}</span>,
          ])}
        />
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {(output.assumptions || []).length > 0 && (
          <div className="rounded-lg border border-border bg-secondary/30 px-3 py-3 text-xs">
            <div className="font-semibold mb-2">Assumptions</div>
            <div className="space-y-1 text-muted-foreground">{(output.assumptions || []).map((item: string, index: number) => <div key={index}>- {item}</div>)}</div>
          </div>
        )}
        {(output.exclusions || []).length > 0 && (
          <div className="rounded-lg border border-border bg-secondary/30 px-3 py-3 text-xs">
            <div className="font-semibold mb-2">Exclusions</div>
            <div className="space-y-1 text-muted-foreground">{(output.exclusions || []).map((item: string, index: number) => <div key={index}>- {item}</div>)}</div>
          </div>
        )}
      </div>
    </OutputAccordion>
  );
}

function renderE2(output: RecordLike) {
  const checks = Array.isArray(output.compliance_checks) ? output.compliance_checks : [];
  const blocks = Array.isArray(output.block_reasons) ? output.block_reasons : [];
  return (
    <OutputAccordion title="E2 Legal & Compliance" defaultOpen>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Decision" value={String(output.decision || 'APPROVED').toUpperCase()} tone={String(output.decision || 'APPROVED').toUpperCase() === 'APPROVED' ? 'success' : 'warning'} />
        <StatCard label="Checks" value={checks.length} />
        <StatCard label="Blockers" value={blocks.length} tone={blocks.length ? 'danger' : 'success'} />
        <StatCard label="Confidence" value={`${Math.round(Number(output.confidence || 0) * 100)}%`} />
      </div>
      {blocks.length > 0 && (
        <div className="rounded-lg border border-error/20 bg-error/10 px-3 py-2 text-xs text-muted-foreground">
          <div className="font-semibold text-error mb-1">Blocking reasons</div>
          <div className="space-y-1">{blocks.map((block: string, index: number) => <div key={index}>- {block}</div>)}</div>
        </div>
      )}
      {output.risk_register_summary && (
        <div className="rounded-lg border border-border bg-secondary/30 px-3 py-3 text-xs text-muted-foreground whitespace-pre-wrap">
          <div className="font-semibold text-foreground mb-1">Risk register summary</div>
          {output.risk_register_summary}
        </div>
      )}
      {checks.length > 0 && (
        <SimpleTable
          headers={['Certification', 'Status', 'Gap Severity']}
          rows={checks.map((check: any) => [
            <span key="cert" className="font-semibold">{check.certification || '-'}</span>,
            <Chip key="held" tone={check.held ? 'success' : 'danger'}>{check.held ? 'HELD' : 'MISSING'}</Chip>,
            check.held ? '-' : <Chip key="severity" tone={String(check.gap_severity || '').toUpperCase() === 'CRITICAL' ? 'danger' : String(check.gap_severity || '').toUpperCase() === 'HIGH' ? 'warning' : 'default'}>{String(check.gap_severity || 'low').toUpperCase()}</Chip>,
          ])}
        />
      )}
    </OutputAccordion>
  );
}

export default function AgentOutputs({ outputs }: { outputs: any }) {
  if (!outputs || Object.keys(outputs).length === 0) {
    return <div className="p-6 text-sm text-muted-foreground italic flex justify-center">No agent outputs available for this run.</div>;
  }

  return (
    <div className="p-6 space-y-3">
      <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-[0.1em] mb-4">Agent Outputs</h3>

      {outputs.A1_INTAKE && (
        <OutputAccordion title="A1 Intake" defaultOpen>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div><strong>RFP ID:</strong> {outputs.A1_INTAKE.rfp_id || '-'}</div>
            <div><strong>Title:</strong> {outputs.A1_INTAKE.title || '-'}</div>
            <div><strong>Pages:</strong> {outputs.A1_INTAKE.page_count ?? '-'}</div>
            <div><strong>Words:</strong> {outputs.A1_INTAKE.word_count ?? '-'}</div>
          </div>
        </OutputAccordion>
      )}

      {outputs.A2_STRUCTURING && (
        <OutputAccordion title="A2 Structuring">
          <div className="space-y-3">
            {(outputs.A2_STRUCTURING.sections || []).map((section: any, index: number) => (
              <div key={index} className="text-xs">
                <span className="px-1.5 py-0.5 rounded bg-secondary text-primary font-semibold mr-2">{section.category}</span>
                <strong>{section.title}</strong> - <span className="text-muted-foreground">{section.content_summary}</span>
              </div>
            ))}
          </div>
        </OutputAccordion>
      )}

      {outputs.A3_GO_NO_GO && (
        <OutputAccordion title={`A3 Go/No-Go - ${outputs.A3_GO_NO_GO.decision}`}>
          <div className="space-y-3 text-xs">
            <div className="flex gap-4 mb-2 flex-wrap">
              <div><strong>Strategic Fit:</strong> {outputs.A3_GO_NO_GO.strategic_fit_score ?? '-'}/10</div>
              <div><strong>Technical:</strong> {outputs.A3_GO_NO_GO.technical_feasibility_score ?? '-'}/10</div>
              <div><strong>Risk:</strong> {outputs.A3_GO_NO_GO.regulatory_risk_score ?? '-'}/10</div>
            </div>
            <div><strong>Justification:</strong> {outputs.A3_GO_NO_GO.justification || '-'}</div>
          </div>
        </OutputAccordion>
      )}

      {outputs.B1_REQUIREMENTS_EXTRACTION && (
        <OutputAccordion title={`B1 Requirements Extraction (${outputs.B1_REQUIREMENTS_EXTRACTION.length} total)`}>
          <SimpleTable
            headers={['ID', 'Type', 'Class', 'Requirement']}
            rows={(outputs.B1_REQUIREMENTS_EXTRACTION || []).map((requirement: any) => [
              <span key="id" className="font-semibold text-primary">{requirement.requirement_id}</span>,
              requirement.type || '-',
              <Chip key="class" tone="accent">{requirement.classification || '-'}</Chip>,
              <span key="text" className="max-w-sm block">{requirement.text || '-'}</span>,
            ])}
          />
        </OutputAccordion>
      )}

      {outputs.B2_REQUIREMENTS_VALIDATION && renderB2(outputs.B2_REQUIREMENTS_VALIDATION)}
      {outputs.C1_ARCHITECTURE_PLANNING && renderC1(outputs.C1_ARCHITECTURE_PLANNING)}
      {outputs.C2_REQUIREMENT_WRITING && renderC2(outputs.C2_REQUIREMENT_WRITING)}
      {outputs.C3_NARRATIVE_ASSEMBLY && renderC3(outputs.C3_NARRATIVE_ASSEMBLY)}
      {outputs.D1_TECHNICAL_VALIDATION && renderD1(outputs.D1_TECHNICAL_VALIDATION)}
      {outputs.E1_COMMERCIAL && renderE1(outputs.E1_COMMERCIAL)}
      {outputs.E2_LEGAL && renderE2(outputs.E2_LEGAL)}

      {Object.entries(outputs).filter(([key]) => ![
        'A1_INTAKE',
        'A2_STRUCTURING',
        'A3_GO_NO_GO',
        'B1_REQUIREMENTS_EXTRACTION',
        'B2_REQUIREMENTS_VALIDATION',
        'C1_ARCHITECTURE_PLANNING',
        'C2_REQUIREMENT_WRITING',
        'C3_NARRATIVE_ASSEMBLY',
        'D1_TECHNICAL_VALIDATION',
        'E1_COMMERCIAL',
        'E2_LEGAL',
      ].includes(key)).map(([key, value]) => (
        <OutputAccordion key={key} title={key}>
          <JsonFallback value={value} />
        </OutputAccordion>
      ))}
    </div>
  );
}
