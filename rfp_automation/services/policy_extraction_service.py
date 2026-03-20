"""
Policy Extraction Service — extract rules, policies, certifications from
company documents using the LLM at upload time.

Persists results to extracted_policies.json as the single source of truth.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfp_automation.services.llm_service import llm_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "policy_extraction_prompt.txt"
_POLICIES_PATH = Path(__file__).resolve().parent.parent / "mcp" / "knowledge_data" / "extracted_policies.json"


class PolicyExtractionService:
    """Extract and persist company policies from uploaded documents."""

    # ── Public API ───────────────────────────────────

    def extract_and_persist(
        self,
        doc_id: str,
        doc_type: str,
        texts: list[str],
        filename: str,
    ) -> list[dict[str, Any]]:
        """
        Extract policies from document text via LLM and append to the
        persisted JSON file.  Returns list of newly extracted policies.
        Processes in small batches to avoid LLM token limits and JSON truncation.
        """
        import time
        # Determine next POL-ID
        existing = self._load_policies()
        start_id = self._next_policy_number(existing)

        # Batch texts to prevent hitting max response length
        BATCH_SIZE = 15
        all_new_policies = []
        
        logger.info(f"[PolicyExtraction] Extracting policies from {filename} ({len(texts)} blocks in batches of {BATCH_SIZE})…")

        for i in range(0, min(len(texts), 90), BATCH_SIZE):  # Process up to first 90 chunks
            batch_texts = texts[i:i + BATCH_SIZE]
            combined_text = "\n".join(batch_texts)
            prompt = self._build_prompt(combined_text, doc_type, filename, start_id)
            
            logger.debug(f"[PolicyExtraction] Processing batch {i//BATCH_SIZE + 1}...")

            try:
                raw_response = llm_text_call(prompt, max_retries=1)
                
                if not raw_response.strip():
                    logger.warning(f"[PolicyExtraction] Empty response for batch {i//BATCH_SIZE + 1} of {filename}")
                    continue

                batch_policies = self._parse_response(raw_response)
                
                if batch_policies:
                    all_new_policies.extend(batch_policies)
                    start_id += len(batch_policies)
                    logger.debug(f"[PolicyExtraction] Extracted {len(batch_policies)} policies from batch {i//BATCH_SIZE + 1}")
                else:
                    logger.warning(f"[PolicyExtraction] No valid JSON policies from batch {i//BATCH_SIZE + 1}")
                    
            except Exception as e:
                logger.error(f"[PolicyExtraction] Error evaluating batch {i//BATCH_SIZE + 1}: {e}")
            
            # Brief sleep to avoid rapid rate limits
            time.sleep(1)

        new_policies = all_new_policies

        # Enrich with metadata
        now = datetime.now(timezone.utc).isoformat()
        for pol in new_policies:
            pol["source_doc_id"] = doc_id
            pol["source_filename"] = filename
            pol["created_at"] = now
            pol["is_manually_added"] = False

        # Persist
        all_policies = existing + new_policies
        self._save_policies(all_policies)

        logger.info(f"[PolicyExtraction] Extracted {len(new_policies)} policies from {filename}")
        return new_policies

    # ── CRUD helpers (used by API routes) ────────────

    @staticmethod
    def get_all_policies() -> list[dict[str, Any]]:
        """Return all persisted policies."""
        return PolicyExtractionService._load_policies_static()

    @staticmethod
    def add_policy(policy: dict[str, Any]) -> dict[str, Any]:
        """Add a manually created policy."""
        policies = PolicyExtractionService._load_policies_static()

        # Generate next ID
        start = PolicyExtractionService._next_policy_number_static(policies)
        policy["policy_id"] = f"POL-{start:03d}"
        policy["created_at"] = datetime.now(timezone.utc).isoformat()
        policy["is_manually_added"] = True
        policy.setdefault("source_doc_id", "")
        policy.setdefault("source_filename", "manual")

        policies.append(policy)
        PolicyExtractionService._save_policies_static(policies)
        return policy

    @staticmethod
    def update_policy(policy_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update an existing policy by ID.  Returns updated policy or None."""
        policies = PolicyExtractionService._load_policies_static()
        for pol in policies:
            if pol.get("policy_id") == policy_id:
                allowed = {"policy_text", "category", "rule_type", "severity", "source_section"}
                for key in allowed:
                    if key in updates:
                        pol[key] = updates[key]
                pol["updated_at"] = datetime.now(timezone.utc).isoformat()
                PolicyExtractionService._save_policies_static(policies)
                return pol
        return None

    @staticmethod
    def delete_policy(policy_id: str) -> bool:
        """Delete a policy by ID.  Returns True if found and deleted."""
        policies = PolicyExtractionService._load_policies_static()
        original_len = len(policies)
        policies = [p for p in policies if p.get("policy_id") != policy_id]
        if len(policies) == original_len:
            return False
        PolicyExtractionService._save_policies_static(policies)
        return True

    # ── Internal helpers ─────────────────────────────

    def _build_prompt(
        self, document_text: str, doc_type: str, filename: str, start_id: int
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return template.replace("{document_text}", document_text[:15_000]).replace(
            "{doc_type}", doc_type
        ).replace("{filename}", filename).replace("{start_id}", str(start_id))

    def _parse_response(self, raw: str) -> list[dict[str, Any]]:
        """Parse LLM response into list of policy dicts."""
        # Strip markdown fencing if present
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        # Try to find JSON array
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [self._validate_policy(p) for p in data if isinstance(p, dict)]
        except json.JSONDecodeError:
            pass

        # Fallback: find first [ ... ] in the response
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return [self._validate_policy(p) for p in data if isinstance(p, dict)]
            except json.JSONDecodeError:
                pass

        logger.error("[PolicyExtraction] Failed to parse LLM response as JSON array")
        return []

    @staticmethod
    def _validate_policy(p: dict) -> dict:
        """Ensure required fields exist with defaults."""
        VALID_CATEGORIES = {"certification", "legal", "compliance", "operational",
                            "commercial", "governance", "capability"}
        VALID_RULE_TYPES = {"constraint", "requirement", "capability", "prohibition",
                            "threshold", "standard"}
        VALID_SEVERITIES = {"critical", "high", "medium", "low"}

        p.setdefault("policy_id", "POL-000")
        p.setdefault("policy_text", "")
        cat = p.get("category", "").lower()
        p["category"] = cat if cat in VALID_CATEGORIES else "capability"
        rt = p.get("rule_type", "").lower()
        p["rule_type"] = rt if rt in VALID_RULE_TYPES else "requirement"
        sev = p.get("severity", "").lower()
        p["severity"] = sev if sev in VALID_SEVERITIES else "medium"
        p.setdefault("source_section", "")
        return p

    def _load_policies(self) -> list[dict[str, Any]]:
        return self._load_policies_static()

    def _save_policies(self, policies: list[dict[str, Any]]) -> None:
        self._save_policies_static(policies)

    def _next_policy_number(self, policies: list[dict]) -> int:
        return self._next_policy_number_static(policies)

    @staticmethod
    def _load_policies_static() -> list[dict[str, Any]]:
        if not _POLICIES_PATH.exists():
            return []
        try:
            data = json.loads(_POLICIES_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _save_policies_static(policies: list[dict[str, Any]]) -> None:
        os.makedirs(_POLICIES_PATH.parent, exist_ok=True)
        _POLICIES_PATH.write_text(
            json.dumps(policies, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _next_policy_number_static(policies: list[dict]) -> int:
        max_num = 0
        for p in policies:
            pid = p.get("policy_id", "")
            match = re.search(r"POL-(\d+)", pid)
            if match:
                max_num = max(max_num, int(match.group(1)))
        return max_num + 1

    # ── Derived file sync ────────────────────────────

    # Categories that map to capabilities.json
    _CAPABILITY_CATEGORIES = {"capability", "governance", "operational"}
    # Categories that map to certifications.json
    _CERTIFICATION_CATEGORIES = {"certification", "compliance"}
    # Categories that map to pricing_rules.json
    _PRICING_CATEGORIES = {"commercial"}
    # Categories that map to legal_templates.json
    _LEGAL_CATEGORIES = {"legal", "privacy", "compliance"}
    # Categories that map to past_proposals.json
    _PROPOSAL_CATEGORIES = {"experience", "case_study", "past_performance"}

    @staticmethod
    def sync_derived_files() -> dict[str, int]:
        """Derive capabilities.json, certifications.json, pricing_rules.json,
        legal_templates.json, and past_proposals.json from extracted_policies.json.

        Called after each document upload to keep the structured KB files
        in sync with the LLM-extracted policies. Returns counts of
        entries written to each file.
        """
        policies = PolicyExtractionService._load_policies_static()
        if not policies:
            logger.info("[PolicySync] No extracted policies — skipping sync")
            return {
                "capabilities": 0, "certifications": 0, "pricing": 0,
                "legal": 0, "proposals": 0
            }

        data_dir = _POLICIES_PATH.parent

        # ── Build capabilities ──────────────────────────
        caps: list[dict] = []
        for i, pol in enumerate(policies):
            cat = pol.get("category", "")
            if cat not in PolicyExtractionService._CAPABILITY_CATEGORIES:
                continue

            text = pol.get("policy_text", "").strip()
            if not text or len(text) < 10:
                continue

            # Derive a short name from the first sentence / 80 chars
            name = text.split(".")[0][:80].strip()
            if not name:
                name = text[:80]

            # Extract keyword-style tags from the text
            tags = _extract_tags(text)

            caps.append({
                "id": f"cap-doc-{i:03d}",
                "name": name,
                "description": text[:500],
                "category": cat,
                "tags": tags,
                "evidence": pol.get("source_section", ""),
                "source_policy_id": pol.get("policy_id", ""),
            })

        # ── Build certifications ────────────────────────
        certs: dict[str, bool] = {}
        for pol in policies:
            cat = pol.get("category", "")
            if cat not in PolicyExtractionService._CERTIFICATION_CATEGORIES:
                continue

            text = pol.get("policy_text", "").strip()
            if not text:
                continue

            # Use the first sentence as the cert name
            cert_name = text.split(".")[0][:100].strip()
            if cert_name:
                certs[cert_name] = True

        # ── Build pricing rules ─────────────────────────
        pricing_entries: list[dict] = []
        for pol in policies:
            cat = pol.get("category", "")
            if cat not in PolicyExtractionService._PRICING_CATEGORIES:
                continue

            text = pol.get("policy_text", "").strip()
            if not text:
                continue

            pricing_entries.append({
                "text": text,
                "source_section": pol.get("source_section", ""),
                "source_policy_id": pol.get("policy_id", ""),
            })

        pricing_rules = _build_pricing_rules(pricing_entries)

        # ── Build legal templates ───────────────────────
        legal_entries: list[dict] = []
        for pol in policies:
            cat = pol.get("category", "")
            if cat not in PolicyExtractionService._LEGAL_CATEGORIES:
                continue
            text = pol.get("policy_text", "").strip()
            if text:
                legal_entries.append({"text": text, "id": pol.get("policy_id", "")})

        legal_templates = _build_legal_templates(legal_entries)

        # ── Build past proposals ────────────────────────
        proposal_entries: list[dict] = []
        for pol in policies:
            cat = pol.get("category", "")
            if cat not in PolicyExtractionService._PROPOSAL_CATEGORIES:
                continue
            text = pol.get("policy_text", "").strip()
            if text:
                proposal_entries.append({"text": text, "id": pol.get("policy_id", "")})

        past_proposals = _build_past_proposals(proposal_entries)

        # ── Write files ─────────────────────────────────
        caps_path = data_dir / "capabilities.json"
        caps_path.write_text(
            json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        certs_path = data_dir / "certifications.json"
        certs_path.write_text(
            json.dumps(certs, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        pricing_path = data_dir / "pricing_rules.json"
        pricing_path.write_text(
            json.dumps(pricing_rules, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        legal_path = data_dir / "legal_templates.json"
        if legal_templates:  # Only overwrite if we found some
            legal_path.write_text(
                json.dumps(legal_templates, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        proposals_path = data_dir / "past_proposals.json"
        if past_proposals:  # Only overwrite if we found some
            proposals_path.write_text(
                json.dumps(past_proposals, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        logger.info(
            f"[PolicySync] Synced {len(caps)} capabilities, "
            f"{len(certs)} certifications, "
            f"{len(pricing_entries)} pricing entries, "
            f"{len(legal_templates)} legal templates, "
            f"{len(past_proposals)} proposals from {len(policies)} policies"
        )
        return {
            "capabilities": len(caps),
            "certifications": len(certs),
            "pricing": len(pricing_entries),
            "legal": len(legal_templates),
            "proposals": len(past_proposals),
        }


def _extract_tags(text: str) -> list[str]:
    """Extract simple keyword tags from policy text."""
    # Common domain keywords to look for
    _KEYWORDS = [
        "cloud", "security", "compliance", "api", "5g", "bss", "oss",
        "billing", "charging", "fraud", "revenue", "sla", "kubernetes",
        "devops", "automation", "ai", "ml", "analytics", "migration",
        "telecom", "network", "infrastructure", "monitoring", "testing",
        "certification", "iso", "soc", "pci", "gdpr", "trai", "gst",
        "tmf", "3gpp", "diameter", "sip", "nfv", "sdn", "iot",
        "microservices", "container", "docker", "agile", "ci-cd",
        "encryption", "authentication", "rbac", "saml", "oauth",
    ]
    text_lower = text.lower()
    return [kw for kw in _KEYWORDS if kw in text_lower][:8]  # cap at 8 tags


def _build_pricing_rules(entries: list[dict]) -> dict:
    """Build a pricing_rules.json structure from commercial policy entries.

    Parses commercial policy texts for currency, cost figures, payment terms,
    and discount details. Returns a structured dict for the commercial agent.
    """
    if not entries:
        return {"source": "extracted", "entries": [], "currency": "", "payment_terms": ""}

    all_texts = " ".join(e.get("text", "") for e in entries)

    # Detect currency from texts
    currency = ""
    if re.search(r"\bINR\b|₹|\bRupee|Crore|Lakh", all_texts, re.IGNORECASE):
        currency = "INR"
    elif re.search(r"\bUSD\b|\$|\bDollar", all_texts, re.IGNORECASE):
        currency = "USD"

    # Extract payment terms
    payment_terms = ""
    pt_match = re.search(
        r"(?:payment\s+terms?|payment\s+schedule|billing\s+cycle)[:\s]+([^\n.]{10,100})",
        all_texts, re.IGNORECASE,
    )
    if pt_match:
        payment_terms = pt_match.group(1).strip()

    # Extract discount info
    discount_info = ""
    disc_match = re.search(
        r"(?:discount|rebate|concession)[:\s]+([^\n.]{10,100})",
        all_texts, re.IGNORECASE,
    )
    if disc_match:
        discount_info = disc_match.group(1).strip()

    return {
        "source": "extracted",
        "currency": currency,
        "payment_terms": payment_terms,
        "discount_info": discount_info,
        "entries": [
            {
                "text": e.get("text", ""),
                "source_section": e.get("source_section", ""),
                "source_policy_id": e.get("source_policy_id", ""),
            }
            for e in entries
        ],
    }


def _build_legal_templates(entries: list[dict]) -> list[dict]:
    """Parse legal policies into legal_templates.json structure.
    
    Extracts clause snippets and constructs standard legal template blocks.
    """
    templates: list[dict] = []
    for i, e in enumerate(entries):
        text = e.get("text", "")
        if len(text) < 20:
            continue
            
        # VERY basic inference of clause type from keywords
        text_lower = text.lower()
        clause_type = "general"
        if "liab" in text_lower: clause_type = "limitation_of_liability"
        elif "ip " in text_lower or "intellectual" in text_lower: clause_type = "intellectual_property"
        elif "indemn" in text_lower: clause_type = "indemnification"
        elif "terminat" in text_lower: clause_type = "termination"
        elif "data" in text_lower or "gdpr" in text_lower: clause_type = "data_protection"
        elif "warrant" in text_lower: clause_type = "warranty"
        elif "confidential" in text_lower: clause_type = "confidentiality"
        
        # Use first 150 chars as acceptable template, note it otherwise
        templates.append({
            "id": f"leg-doc-{i:03d}",
            "clause_type": clause_type,
            "acceptable_template": text[:200].strip() + ("..." if len(text) > 200 else ""),
            "risk_threshold": f"Deviation from standard {clause_type}",
            "auto_block": False,
            "notes": text[:500] if len(text) > 200 else "Standard provision extracted from KB."
        })
    return templates


def _build_past_proposals(entries: list[dict]) -> list[dict]:
    """Parse experience/case_study policies into past_proposals.json structure."""
    proposals: list[dict] = []
    for i, e in enumerate(entries):
        text = e.get("text", "")
        if len(text) < 20:
            continue
            
        # First sentence as title
        title = text.split(".")[0][:100].strip()
        
        # Look for outcome-like keywords for the outcome
        outcome = "Completed successfully."
        out_match = re.search(r"(?:resulted in|achieved|outcome:?|won\s+-?)[^\n]{10,120}", text, re.IGNORECASE)
        if out_match:
            outcome = out_match.group(0).strip()
            
        tags = _extract_tags(text)
        
        proposals.append({
            "id": f"prop-doc-{i:03d}",
            "title": title,
            "category": tags[0] if tags else "experience",
            "excerpt": text[:600] + ("..." if len(text) > 600 else ""),
            "outcome": outcome,
            "tags": tags
        })
    return proposals


