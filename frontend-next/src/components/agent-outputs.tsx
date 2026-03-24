import { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';

export default function AgentOutputs({ outputs }: { outputs: any }) {
  if (!outputs || Object.keys(outputs).length === 0) {
    return <div className="p-6 text-sm text-muted-foreground italic flex justify-center">No agent outputs available for this run.</div>;
  }

  return (
    <div className="p-6 space-y-3">
      <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-[0.1em] mb-4">Agent Outputs</h3>
      
      {outputs.A1_INTAKE && (
        <OutputAccordion title="📥 A1 Intake" defaultOpen>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div><strong>RFP ID:</strong> {outputs.A1_INTAKE.rfp_id || '—'}</div>
            <div><strong>Title:</strong> {outputs.A1_INTAKE.title || '—'}</div>
            <div><strong>Pages:</strong> {outputs.A1_INTAKE.page_count ?? '—'}</div>
            <div><strong>Words:</strong> {outputs.A1_INTAKE.word_count ?? '—'}</div>
          </div>
        </OutputAccordion>
      )}

      {outputs.A2_STRUCTURING && (
        <OutputAccordion title="📑 A2 Structuring">
          <div className="space-y-3">
            {(outputs.A2_STRUCTURING.sections || []).map((s: any, i: number) => (
              <div key={i} className="text-xs">
                <span className="px-1.5 py-0.5 rounded bg-secondary text-primary font-semibold mr-2">{s.category}</span>
                <strong>{s.title}</strong> &mdash; <span className="text-muted-foreground">{s.content_summary}</span>
              </div>
            ))}
          </div>
        </OutputAccordion>
      )}

      {outputs.A3_GO_NO_GO && (
        <OutputAccordion title={`📊 A3 Go/No-Go — ${outputs.A3_GO_NO_GO.decision}`}>
          <div className="space-y-3 text-xs">
             <div className="flex gap-4 mb-2">
               <div><strong>Strategic Fit:</strong> {outputs.A3_GO_NO_GO.strategic_fit_score ?? '—'}/10</div>
               <div><strong>Technical:</strong> {outputs.A3_GO_NO_GO.technical_feasibility_score ?? '—'}/10</div>
               <div><strong>Risk:</strong> {outputs.A3_GO_NO_GO.regulatory_risk_score ?? '—'}/10</div>
             </div>
             <div><strong>Justification:</strong> {outputs.A3_GO_NO_GO.justification || '—'}</div>
          </div>
        </OutputAccordion>
      )}

      {outputs.B1_REQUIREMENTS_EXTRACTION && (
        <OutputAccordion title={`🔍 B1 Requirements Extraction (${outputs.B1_REQUIREMENTS_EXTRACTION.length} total)`}>
          <div className="max-h-64 overflow-y-auto border border-border rounded-md">
            <table className="w-full text-xs text-left">
              <thead className="sticky top-0 bg-secondary border-b border-border">
                <tr>
                  <th className="p-2">ID</th><th className="p-2">Type</th><th className="p-2">Class</th><th className="p-2">Requirement</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {outputs.B1_REQUIREMENTS_EXTRACTION.map((r: any, i: number) => (
                  <tr key={i} className="hover:bg-muted/10">
                    <td className="p-2 font-semibold text-primary">{r.requirement_id}</td>
                    <td className="p-2">{r.type}</td>
                    <td className="p-2">
                      <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-semibold">{r.classification}</span>
                    </td>
                    <td className="p-2 max-w-sm align-top">{r.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </OutputAccordion>
      )}

      {/* Very simplified implementations for the rest using JSON viewers to ensure parital parity instantly, then refined if needed */}
      {outputs.B2_REQUIREMENTS_VALIDATION && (
        <OutputAccordion title="🛡️ B2 Requirements Validation">
          <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(outputs.B2_REQUIREMENTS_VALIDATION, null, 2)}</pre>
        </OutputAccordion>
      )}
      
      {outputs.C1_ARCHITECTURE_PLANNING && (
        <OutputAccordion title="🏗️ C1 Architecture Planning">
          <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(outputs.C1_ARCHITECTURE_PLANNING, null, 2)}</pre>
        </OutputAccordion>
      )}

      {outputs.C2_REQUIREMENT_WRITING && (
        <OutputAccordion title="✍️ C2 Requirement Writing">
          <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(outputs.C2_REQUIREMENT_WRITING, null, 2)}</pre>
        </OutputAccordion>
      )}

      {outputs.C3_NARRATIVE_ASSEMBLY && (
        <OutputAccordion title="📄 C3 Narrative Assembly">
           <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(outputs.C3_NARRATIVE_ASSEMBLY, null, 2)}</pre>
        </OutputAccordion>
      )}

      {outputs.D1_TECHNICAL_VALIDATION && (
        <OutputAccordion title="🔍 D1 Technical Validation">
           <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(outputs.D1_TECHNICAL_VALIDATION, null, 2)}</pre>
        </OutputAccordion>
      )}

      {outputs.E1_COMMERCIAL && (
        <OutputAccordion title="💰 E1 Commercial Review">
           <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(outputs.E1_COMMERCIAL, null, 2)}</pre>
        </OutputAccordion>
      )}

      {outputs.E2_LEGAL && (
        <OutputAccordion title="⚖️ E2 Legal Review">
           <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">{JSON.stringify(outputs.E2_LEGAL, null, 2)}</pre>
        </OutputAccordion>
      )}
    </div>
  );
}

function OutputAccordion({ title, children, defaultOpen = false }: { title: string, children: React.ReactNode, defaultOpen?: boolean }) {
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
      {open && (
        <div className="p-4 border-t border-border bg-card/50">
          {children}
        </div>
      )}
    </div>
  );
}
