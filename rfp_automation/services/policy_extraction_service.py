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
        """
        # Determine next POL-ID
        existing = self._load_policies()
        start_id = self._next_policy_number(existing)

        # Build prompt
        combined_text = "\n".join(texts[:50])  # first 50 blocks
        prompt = self._build_prompt(combined_text, doc_type, filename, start_id)

        # Call LLM with retries on empty responses
        logger.info(f"[PolicyExtraction] Extracting policies from {filename} ({len(texts)} blocks)…")
        raw_response = llm_text_call(prompt, max_retries=2)

        if not raw_response.strip():
            logger.error(
                f"[PolicyExtraction] LLM returned empty response after all retries "
                f"for {filename} — no policies extracted"
            )
            return []

        # Parse
        new_policies = self._parse_response(raw_response)
        if not new_policies:
            logger.warning(f"[PolicyExtraction] No policies extracted from {filename}")
            return []

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
