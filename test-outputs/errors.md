======================================================================
Pipeline Run — 2026-03-22T16:20:45.456191 — RFP: RFP-B8C6F1C0
Total records: 29
======================================================================

2026-03-22 15:58:18 | WARNING | huggingface_hub.utils._http | Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads.
2026-03-22 16:03:28 | ERROR   | rfp_automation.mcp.vector_store.rfp_store | [RFP-BFF808FA] Failed to delete: (404)
Reason: Not Found
HTTP response headers: HTTPHeaderDict({'Date': 'Sun, 22 Mar 2026 10:33:34 GMT', 'Content-Type': 'application/json', 'Content-Length': '55', 'Connection': 'keep-alive', 'x-pinecone-request-latency-ms': '31', 'x-envoy-upstream-service-time': '32', 'x-pinecone-response-duration-ms': '33', 'server': 'envoy'})
HTTP response body: {"code":5,"message":"Namespace not found","details":[]}

2026-03-22 16:08:14 | WARNING | rfp_automation.agents.structuring_agent | [A2] No JSON array found in LLM response
2026-03-22 16:10:40 | WARNING | rfp_automation.agents.structuring_agent | [A2] No JSON array found in LLM response
2026-03-22 16:11:59 | WARNING | rfp_automation.agents.structuring_agent | [A2] No JSON array found in LLM response
2026-03-22 16:14:37 | WARNING | rfp_automation.agents.structuring_agent | [A2] JSON parse error: Expecting value: line 1 column 2 (char 1)
2026-03-22 16:16:31 | WARNING | rfp_automation.agents.requirement_extraction_agent | [B1] Candidate density 4.66% is suspiciously low. Falling back to full text extraction for section 'Legal Disclaimer and Confidentiality Notice'.
2026-03-22 16:16:40 | WARNING | rfp_automation.agents.requirement_extraction_agent | [B1] Candidate density 13.32% is suspiciously low. Falling back to full text extraction for section 'SECTION 1 — Executive Summary and Introduction > 1.2  Current Infrastructure Challenges and Business Drivers > Chronic Network 
Outages'.
2026-03-22 16:16:50 | WARNING | rfp_automation.services.llm_service | [LLM-DET] Rate limit hit (attempt 1/2). Waiting 10s...
2026-03-22 16:17:00 | ERROR   | rfp_automation.services.llm_service | [LLM-DET] Rate limit exceeded on final attempt: Error code: 413 - {'error': {'message': 'Request too large for model `qwen/qwen3-32b` in organization `org_01k1br6174ftptdxjm9rkjja9f` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Requested 26249, please reduce your message size and try again. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
2026-03-22 16:17:00 | ERROR   | rfp_automation.agents.requirement_extraction_agent | [B1] LLM batch call failed unexpectedly: Error code: 413 - {'error': {'message': 'Request too large for model `qwen/qwen3-32b` in organization `org_01k1br6174ftptdxjm9rkjja9f` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Requested 26249, please reduce your message size and try again. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
2026-03-22 16:17:01 | WARNING | rfp_automation.services.llm_service | [LLM-DET] Rate limit hit (attempt 1/2). Waiting 10s...
2026-03-22 16:17:12 | ERROR   | rfp_automation.services.llm_service | [LLM-DET] Rate limit exceeded on final attempt: Error code: 413 - {'error': {'message': 'Request too large for model `qwen/qwen3-32b` in organization `org_01k1tcbr8yfjpr4twps8ab1y3t` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Requested 25562, please reduce your message size and try again. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
2026-03-22 16:17:12 | ERROR   | rfp_automation.agents.requirement_extraction_agent | [B1] LLM batch call failed unexpectedly: Error code: 413 - {'error': {'message': 'Request too large for model `qwen/qwen3-32b` in organization `org_01k1tcbr8yfjpr4twps8ab1y3t` service tier `on_demand` on tokens per minute (TPM): Limit 6000, Requested 25562, please reduce your message size and try again. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}
2026-03-22 16:17:13 | WARNING | rfp_automation.agents.requirement_extraction_agent | [B1] ⚠ LOW COVERAGE: Only 10 requirements extracted from 971 obligation indicators (ratio=0.01, threshold=0.6). Review may be needed.
2026-03-22 16:17:16 | WARNING | rfp_automation.agents.requirement_validation_agent | [B2] 1 factual error(s) detected — extracted values don't match RFP source text
2026-03-22 16:19:07 | WARNING | rfp_automation.agents.writing_agent | [C2] Company profile exists in MongoDB but has no company_name
2026-03-22 16:19:12 | WARNING | rfp_automation.agents.writing_agent | [C2] 1 placeholder(s) in SEC-01: ['[Name]']
2026-03-22 16:19:21 | WARNING | rfp_automation.agents.writing_agent | [C2] ⚠ LOW WORD COUNT: Section SEC-04 (Company Profile and Qualifications) has only 384 words (minimum for knowledge_driven: 400)
2026-03-22 16:19:26 | WARNING | rfp_automation.agents.writing_agent | [C2] Could not parse JSON for section SEC-05 — using raw text as content (recovering REQ-IDs from text)
2026-03-22 16:19:39 | WARNING | rfp_automation.agents.writing_agent | [C2] ⚠ LOW WORD COUNT: Section SEC-08 (Case Studies and Client References) has only 373 words (minimum for knowledge_driven: 400)
2026-03-22 16:19:42 | WARNING | rfp_automation.agents.writing_agent | [C2] 2 placeholder(s) in SEC-11: ['[Insert resumes of key team members]', '[Insert equipment datasheets]']
2026-03-22 16:19:59 | WARNING | rfp_automation.agents.narrative_agent | [C3] Company profile exists in MongoDB but has no company_name
2026-03-22 16:19:59 | WARNING | rfp_automation.agents.narrative_agent | [C3] Company name not found in MongoDB KB profile or config. Placeholders like [Proposing Company] will not be resolved. Set company_name in .env or upload a company profile via the UI.
2026-03-22 16:20:00 | WARNING | rfp_automation.agents.narrative_agent | [C3] Company profile exists in MongoDB but has no company_name
2026-03-22 16:20:00 | WARNING | rfp_automation.agents.narrative_agent | [C3] Company name not found in MongoDB KB profile or config. Placeholders like [Proposing Company] will not be resolved. Set company_name in .env or upload a company profile via the UI.
2026-03-22 16:20:44 | WARNING | rfp_automation.agents.legal_agent | [E2] Block reasons: ['AUTO-BLOCK: unlimited liability', 'AUTO-BLOCK: unlimited liability']
2026-03-22 16:20:44 | WARNING | rfp_automation.orchestration.graph | [GATE] E2 Legal BLOCKED — reasons: ['AUTO-BLOCK: unlimited liability', 'AUTO-BLOCK: unlimited liability']
2026-03-22 16:20:44 | WARNING | rfp_automation.orchestration.transitions | [ROUTING] Commercial/Legal returned BLOCK — bypassing termination, continuing pipeline to Human Validation for testing.

======================================================================
Pipeline Run — 2026-03-22T16:54:01.798723 — RFP: RFP-B8C6F1C0
Total records: 2
======================================================================

2026-03-22 16:54:01 | WARNING | rfp_automation.utils.mermaid_utils | [Mermaid] Mermaid render timed out after 30s
2026-03-22 16:54:01 | WARNING | rfp_automation.agents.final_readiness_agent | [F1] Failed to generate PDF: Command '['python', 'scripts/md_to_pdf.py', 'storage\\submissions\\RFP-BFF808FA\\proposal.md', 'storage\\submissions\\RFP-BFF808FA\\proposal.pdf', '--rfp-title', 'APEX INDUSTRIAL LOGISTICS LIMITED\nRFP Ref: AILL-PROC-2025-0078  |  STRICTLY ', '--client-name', 'Apex']' returned non-zero exit status 1.