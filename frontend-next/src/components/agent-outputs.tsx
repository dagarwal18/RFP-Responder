import { ReactNode, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

type RecordLike = Record<string, any>;

function formatNumber(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString();
  if (typeof value === 'string') return value;
  if (value == null) return '-';
  return String(value);
}

function StatCard({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-sm border border-border px-4 py-3 min-w-[120px]">
      <div className="text-lg font-semibold leading-none text-foreground">{value}</div>
      <div className="mt-2 text-[9px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center rounded-sm bg-secondary px-2 py-0.5 text-[10px] font-semibold text-foreground">{children}</span>;
}

function OutputAccordion({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-border rounded-sm overflow-hidden mb-3">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-3 text-sm font-semibold hover:bg-secondary/50 transition-colors"
      >
        <span className="text-foreground uppercase tracking-widest text-[11px] font-bold">{title}</span>
        {open ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
      </button>
      {open && <div className="p-4 border-t border-border space-y-4">{children}</div>}
    </div>
  );
}

function JsonFallback({ value }: { value: unknown }) {
  return <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap break-all">{JSON.stringify(value, null, 2)}</pre>;
}

function SimpleTable({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto border border-border rounded-sm">
      <table className="w-full text-xs text-left">
        <thead className="border-b border-border bg-transparent">
          <tr>
            {headers.map((header) => <th key={header} className="p-2 font-semibold text-muted-foreground">{header}</th>)}
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
  const requirements = Array.isArray(output.validated_requirements) ? output.validated_requirements : [];
  return (
    <OutputAccordion title="B2 Requirements Validation">
      <div className="flex flex-wrap gap-3">
        <StatCard label="Total Requirements" value={formatNumber(output.total_requirements || requirements.length)} />
      </div>
      {requirements.length > 0 && (
        <SimpleTable
          headers={['ID', 'Type', 'Class', 'Requirement']}
          rows={requirements.map((requirement: any) => [
            <span className="font-semibold text-primary" key="id">{requirement.requirement_id}</span>,
            <Chip key="type">{requirement.type || '-'}</Chip>,
            <Chip key="class">{requirement.classification || '-'}</Chip>,
            <span key="text" className="max-w-xl block text-muted-foreground leading-5">{requirement.text || '-'}</span>,
          ])}
        />
      )}
    </OutputAccordion>
  );
}

function renderC1(output: RecordLike) {
  const sections = Array.isArray(output.sections) ? output.sections : [];
  return (
    <OutputAccordion title={`C1 Architecture Planning (${sections.length} sections)`}>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Sections" value={formatNumber(output.total_sections || sections.length)} />
      </div>
      {output.rfp_response_instructions && (
        <div className="rounded-sm border border-border px-4 py-3 text-xs">
          <div className="font-semibold text-primary mb-2 uppercase tracking-widest text-[10px]">RFP response instructions</div>
          <div className="text-muted-foreground leading-5">{output.rfp_response_instructions}</div>
        </div>
      )}
      {sections.length > 0 && (
        <SimpleTable
          headers={['Section', 'Title', 'Type', 'Priority', 'Description']}
          rows={sections.map((section: any) => [
            <span className="font-semibold text-primary" key="id">{section.section_id}</span>,
            section.title || '-',
            <Chip key="type">{section.section_type || '-'}</Chip>,
            section.priority || '-',
            <span key="desc" className="max-w-xs block text-muted-foreground leading-5">{section.description || '-'}</span>,
          ])}
        />
      )}
    </OutputAccordion>
  );
}

function renderC2(output: RecordLike) {
  const sections = Array.isArray(output.section_responses) ? output.section_responses : [];
  const totalWords = sections.reduce((sum: number, section: any) => sum + Number(section.word_count || 0), 0);
  const coveredRequirements = new Set(sections.flatMap((section: any) => section.requirements_addressed || [])).size;
  return (
    <OutputAccordion title={`C2 Requirement Writing (${sections.length} sections, ${totalWords.toLocaleString()} words)`}>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Sections" value={sections.length} />
        <StatCard label="Total Words" value={totalWords.toLocaleString()} />
        <StatCard label="Reqs Covered" value={coveredRequirements} />
      </div>
      {sections.length > 0 && (
        <div className="space-y-2">
          {sections.map((section: any, index: number) => (
            <details key={index} className="rounded-sm border border-border">
              <summary className="cursor-pointer list-none px-4 py-3 flex items-center justify-between gap-3 text-xs">
                <div>
                  <span className="font-semibold text-primary mr-2 uppercase tracking-widest">{section.section_id}</span>
                  <span className="font-medium text-foreground">{section.title}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <span>{section.word_count || 0} words</span>
                  {(section.requirements_addressed || []).length > 0 && <Chip>{section.requirements_addressed.length} reqs</Chip>}
                </div>
              </summary>
              <div className="px-4 pb-4 space-y-3 text-[13px] border-t border-border pt-4 mt-1">
                <div className="text-foreground whitespace-pre-wrap leading-6">{section.content || '-'}</div>
              </div>
            </details>
          ))}
        </div>
      )}
    </OutputAccordion>
  );
}

function renderC3(output: RecordLike) {
  const executiveSummary = output.executive_summary || '';
  const preview = executiveSummary.length > 500 ? `${executiveSummary.slice(0, 500).trimEnd()}...` : executiveSummary;
  const sectionOrder = Array.isArray(output.section_order) ? output.section_order : [];

  return (
    <OutputAccordion title="C3 Narrative Assembly">
      <div className="flex flex-wrap gap-3">
        <StatCard label="Total Words" value={formatNumber(output.word_count || 0)} />
        <StatCard label="Sections" value={formatNumber(output.sections_included || sectionOrder.length)} />
      </div>
      {preview && (
        <div className="space-y-2">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Executive summary</div>
          <div className="rounded-sm border border-border px-4 py-3 text-xs text-foreground whitespace-pre-wrap leading-6">{preview}</div>
        </div>
      )}
    </OutputAccordion>
  );
}

function renderD1(output: RecordLike) {
  const decision = String(output.decision || 'PASS').toUpperCase();
  const checks = Array.isArray(output.checks) ? output.checks : [];
  return (
    <OutputAccordion title="D1 Technical Validation">
      <div className="flex flex-wrap gap-3">
        <StatCard label="Decision" value={decision} />
      </div>
      {checks.length > 0 && (
        <SimpleTable
          headers={['Check', 'Status', 'Description']}
          rows={checks.map((check: any) => {
            const autoPassed = String(check.description || '').toLowerCase().includes('auto-pass');
            return [
              <span key="name" className="font-semibold capitalize text-foreground">{check.check_name || '-'}</span>,
              <Chip key="status">{check.passed ? (autoPassed ? 'AUTO-PASS' : 'PASS') : 'FAIL'}</Chip>,
              <span key="description" className="text-muted-foreground leading-5">{check.description || '-'}</span>,
            ];
          })}
        />
      )}
    </OutputAccordion>
  );
}

function renderE1(output: RecordLike) {
  const items = Array.isArray(output.line_items) ? output.line_items : [];
  return (
    <OutputAccordion title="E1 Commercial Review">
      <div className="flex flex-wrap gap-3">
        <StatCard label="Decision" value={String(output.decision || 'APPROVED').toUpperCase()} />
        <StatCard label="Total Price" value={`${output.currency || 'USD'} ${formatNumber(output.total_price || 0)}`} />
      </div>
      {items.length > 0 && (
        <SimpleTable
          headers={['Category', 'Label', 'Total']}
          rows={items.map((item: any) => [
            <Chip key="category">{item.category || '-'}</Chip>,
            <span key="label" className="text-foreground">{item.label || '-'}</span>,
            <span key="total" className="font-semibold text-muted-foreground">{output.currency || 'USD'} {formatNumber(item.total || 0)}</span>,
          ])}
        />
      )}
    </OutputAccordion>
  );
}

function renderE2(output: RecordLike) {
  const checks = Array.isArray(output.compliance_checks) ? output.compliance_checks : [];
  const blockReasons = Array.isArray(output.block_reasons) ? output.block_reasons : [];
  return (
    <OutputAccordion title="E2 Legal & Compliance">
      <div className="flex flex-wrap gap-3">
        <StatCard label="Decision" value={String(output.decision || 'APPROVED').toUpperCase()} />
        <StatCard label="Checks" value={checks.length} />
      </div>
      
      {blockReasons.length > 0 && (
        <div className="rounded-sm border border-rose-500/30 bg-rose-500/10 px-4 py-3 mt-3 text-xs">
          <div className="font-semibold text-rose-500 mb-2 uppercase tracking-widest text-[10px]">Block Reasons</div>
          <ul className="list-disc pl-4 text-rose-400 leading-5">
            {blockReasons.map((reason: string, i: number) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {checks.length > 0 && (
        <div className="mt-3">
          <SimpleTable
            headers={['Certification', 'Status']}
            rows={checks.map((check: any) => [
              <span key="cert" className="font-semibold text-foreground">{check.certification || '-'}</span>,
              <Chip key="held">{check.held ? 'HELD' : 'MISSING'}</Chip>,
            ])}
          />
        </div>
      )}
    </OutputAccordion>
  );
}

function renderH1(output: RecordLike) {
  const pkg = output;
  const sourceSections = Array.isArray(pkg.source_sections) ? pkg.source_sections : [];
  const responseSections = Array.isArray(pkg.response_sections) ? pkg.response_sections : [];
  
  return (
    <OutputAccordion title="H1 Human Validation">
      <div className="flex flex-wrap gap-3">
        <StatCard label="Source Sections" value={formatNumber(sourceSections.length)} />
        <StatCard label="Response Sections" value={formatNumber(responseSections.length)} />
        <StatCard label="Open Comments" value={formatNumber(pkg.open_comment_count || 0)} />
      </div>
      {(pkg.decision && pkg.decision.decision) && (
         <div className="rounded-sm border border-border px-4 py-3 text-xs">
           <div className="font-semibold text-primary mb-2 uppercase tracking-widest text-[10px]">Decision Recorded</div>
           <div className="text-muted-foreground leading-5">{pkg.decision.decision} by {pkg.decision.reviewer || 'Unknown reviewer'}</div>
         </div>
      )}
    </OutputAccordion>
  );
}

function renderF1(output: RecordLike) {
  const approval = output;
  const submission = output.submission_record || {};
  return (
    <OutputAccordion title="F1 Final Readiness">
      <div className="flex flex-wrap gap-3">
        <StatCard label="Approval" value={String(approval.approval_decision || 'PENDING').toUpperCase()} />
      </div>

      {submission.archive_path && (
        <div className="rounded-sm border border-border px-4 py-3 text-xs mt-3 flex justify-between items-center">
          <span className="font-semibold text-foreground uppercase tracking-widest text-[10px]">Document Availability</span>
          <span className="text-muted-foreground font-medium">Pipeline artifacts saved. Access via History tab.</span>
        </div>
      )}
    </OutputAccordion>
  );
}

export default function AgentOutputs({ outputs }: { outputs: any }) {
  if (!outputs || Object.keys(outputs).length === 0) {
    return <div className="p-6 text-sm text-muted-foreground italic flex justify-center border-t border-border mt-6">No deliverable outputs available for this run.</div>;
  }

  return (
    <div className="p-8 border-t border-border bg-background">
      <h3 className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.1em] mb-4">Pipeline Deliverables</h3>
      <div className="max-w-[1000px]">

        {outputs.A1_INTAKE && (
          <OutputAccordion title="A1 Intake">
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div><strong className="text-muted-foreground uppercase tracking-widest text-[9px] block mb-1">RFP ID</strong> <span className="text-foreground text-sm">{outputs.A1_INTAKE.rfp_id || '-'}</span></div>
              <div><strong className="text-muted-foreground uppercase tracking-widest text-[9px] block mb-1">Title</strong> <span className="text-foreground text-sm">{outputs.A1_INTAKE.title || '-'}</span></div>
              <div><strong className="text-muted-foreground uppercase tracking-widest text-[9px] block mb-1">Pages</strong> <span className="text-foreground text-sm">{outputs.A1_INTAKE.page_count ?? '-'}</span></div>
              <div><strong className="text-muted-foreground uppercase tracking-widest text-[9px] block mb-1">Words</strong> <span className="text-foreground text-sm">{outputs.A1_INTAKE.word_count ?? '-'}</span></div>
            </div>
          </OutputAccordion>
        )}

        {outputs.A2_STRUCTURING && (
          <OutputAccordion title="A2 Structuring">
            <div className="space-y-4">
              {(outputs.A2_STRUCTURING.sections || []).map((section: any, index: number) => (
                <div key={index} className="text-xs">
                  <Chip>{section.category}</Chip>
                  <div className="mt-2 text-foreground font-medium text-[13px]">{section.title}</div>
                  <div className="mt-1 text-muted-foreground leading-5">{section.content_summary}</div>
                </div>
              ))}
            </div>
          </OutputAccordion>
        )}

        {outputs.A3_GO_NO_GO && (
          <OutputAccordion title={`A3 Go/No-Go`}>
            <div className="space-y-4 text-xs">
              <div className="flex gap-4 flex-wrap">
                <StatCard label="Strategic Fit" value={`${outputs.A3_GO_NO_GO.strategic_fit_score ?? '-'}/10`} />
                <StatCard label="Technical Feasibility" value={`${outputs.A3_GO_NO_GO.technical_feasibility_score ?? '-'}/10`} />
                <StatCard label="Regulatory Risk" value={`${outputs.A3_GO_NO_GO.regulatory_risk_score ?? '-'}/10`} />
              </div>
            </div>
          </OutputAccordion>
        )}

        {outputs.B1_REQUIREMENTS_EXTRACTION && (
          <OutputAccordion title={`B1 Requirements Extraction (${outputs.B1_REQUIREMENTS_EXTRACTION.length} total)`}>
            <SimpleTable
              headers={['ID', 'Type', 'Class', 'Requirement']}
              rows={(outputs.B1_REQUIREMENTS_EXTRACTION || []).map((requirement: any) => [
                <span key="id" className="font-semibold text-primary">{requirement.requirement_id}</span>,
                <Chip key="type">{requirement.type || '-'}</Chip>,
                <Chip key="class">{requirement.classification || '-'}</Chip>,
                <span key="text" className="max-w-sm block text-muted-foreground leading-5">{requirement.text || '-'}</span>,
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
        {outputs.H1_HUMAN_VALIDATION && renderH1(outputs.H1_HUMAN_VALIDATION)}
        {outputs.F1_FINAL_READINESS && renderF1(outputs.F1_FINAL_READINESS)}

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
          'H1_HUMAN_VALIDATION',
          'F1_FINAL_READINESS'
        ].includes(key)).map(([key, value]) => (
          <OutputAccordion key={key} title={key}>
            <JsonFallback value={value} />
          </OutputAccordion>
        ))}

      </div>
    </div>
  );
}
