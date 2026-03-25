"""
E1 — Commercial Agent  (Redesigned — KB-Driven)

Responsibility: Generate a realistic commercial proposal section by analysing
               the RFP requirements and the company's Knowledge Base (Product
               Pricing Catalog, rate cards, terms & conditions, etc.).
               Runs in parallel with E2 Legal.

Processing Flow:
  1. Scope Analysis — count requirements by category
  2. RFP Context — extract pricing/commercial guidelines from the RFP
  3. KB Pricing Data — query knowledge base for product catalogs & rate cards
  4. LLM Pricing Analysis — LLM derives pricing from KB data + RFP scope
  5. Validation — commercial_rules.py checks margins/caps/discounts
  6. Flag missing data — anything not in KB is explicitly flagged
  7. Write CommercialResult to state

Key Principle:
  - ALL pricing figures MUST come from the KB or the RFP.
  - If the KB lacks pricing data, the agent MUST flag it explicitly.
  - The agent MUST NEVER fabricate, assume, or use hardcoded pricing values.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from rfp_automation.agents.base_agent import BaseAgent
from rfp_automation.models.enums import AgentName, PipelineStatus
from rfp_automation.models.state import RFPGraphState
from rfp_automation.models.schemas import CommercialResult, PricingLineItem
from rfp_automation.mcp import MCPService
from rfp_automation.services.llm_service import llm_large_text_call

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "commercial_prompt.txt"
)


class CommercialAgent(BaseAgent):
    name = AgentName.E1_COMMERCIAL

    def _real_process(self, state: RFPGraphState) -> RFPGraphState:
        rfp_id = state.rfp_metadata.rfp_id
        logger.info(f"[E1] Starting commercial analysis for {rfp_id}")

        mcp = MCPService()

        # ── Step 1: Scope Analysis ───────────────────────
        req_counts, total_reqs = self._analyse_scope(state)
        logger.info(
            f"[E1] Scope: {total_reqs} requirements across "
            f"{len(req_counts)} categories"
        )

        # ── Step 2: Extract RFP Commercial Context ───────
        rfp_commercial_context = self._extract_rfp_commercial_context(
            mcp, rfp_id, state,
        )
        logger.info(
            f"[E1] RFP commercial context: {len(rfp_commercial_context)} chars"
        )

        # ── Step 3: Query KB for Pricing Data ────────────
        kb_pricing_data = self._query_kb_pricing(mcp)
        logger.info(
            f"[E1] KB pricing data: {len(kb_pricing_data)} chars"
        )

        # ── Step 4: Build Requirement Details ────────────
        requirements_detail = self._build_requirements_detail(state)

        # ── Step 4b: Detect RFP pricing table layout ─────
        rfp_pricing_layout = self._extract_rfp_pricing_layout(mcp, rfp_id)
        if rfp_pricing_layout:
            logger.info(
                f"[E1] RFP pricing layout detected: {len(rfp_pricing_layout)} chars"
            )

        # ── Step 5: LLM Pricing + Narrative ──────────────
        try:
            llm_result = self._llm_commercial_analysis(
                state=state,
                req_counts=req_counts,
                total_reqs=total_reqs,
                rfp_commercial_context=rfp_commercial_context,
                kb_pricing_data=kb_pricing_data,
                requirements_detail=requirements_detail,
                rfp_pricing_layout=rfp_pricing_layout,
            )
        except Exception as exc:
            logger.error(f"[E1] LLM commercial analysis failed: {exc}")
            llm_result = {
                "line_items": [],
                "total_price": 0.0,
                "currency": "USD",
                "executive_summary": "",
                "commercial_narrative": (
                    "Commercial analysis could not be completed. "
                    "Manual pricing review required."
                ),
                "payment_schedule": [],
                "assumptions": [],
                "exclusions": [],
                "missing_data_flags": [
                    "LLM analysis failed — full manual review required"
                ],
            }

        # ── Step 6: Parse LLM result ─────────────────────
        line_items = self._parse_line_items(llm_result.get("line_items", []))
        total_price = float(llm_result.get("total_price", 0.0))
        currency = llm_result.get("currency", "USD")
        commercial_narrative = llm_result.get("commercial_narrative", "")
        exec_summary = llm_result.get("executive_summary", "")
        payment_schedule = llm_result.get("payment_schedule", [])
        assumptions = llm_result.get("assumptions", [])
        exclusions = llm_result.get("exclusions", [])
        missing_data_flags = [
            re.sub(r"^(?:[-*•]\s*)?(?:⚠\s*)?", "", str(flag)).strip()
            for flag in llm_result.get("missing_data_flags", [])
            if str(flag).strip()
        ]

        # Normalize list→string for narrative fields
        for key in ("executive_summary", "commercial_narrative"):
            val = llm_result.get(key, "")
            if isinstance(val, list):
                llm_result[key] = "\n\n".join(str(p) for p in val)
                if key == "commercial_narrative":
                    commercial_narrative = llm_result[key]
                elif key == "executive_summary":
                    exec_summary = llm_result[key]

        # Prepend executive summary + missing data flags
        narrative_parts = []
        if exec_summary:
            narrative_parts.append(
                f"## Executive Pricing Summary\n\n{exec_summary}"
            )
        if missing_data_flags:
            flags_text = "\n".join(f"- {flag}" for flag in missing_data_flags)
            narrative_parts.append(
                f"## Data Gaps — Requires Manual Review\n\n"
                f"The following pricing information was not available in the "
                f"knowledge base and requires manual input:\n\n{flags_text}"
            )
        if commercial_narrative:
            narrative_parts.append(
                f"## Commercial Terms\n\n{commercial_narrative}"
            )
        full_narrative = "\n\n".join(narrative_parts)

        # ── Step 7: Validation ───────────────────────────
        violations = mcp.commercial_rules.validate_pricing(
            total_price=total_price,
            total_cost=0.0,
            discount_percent=0.0,
            currency=currency,
        )
        validation_flags = [v["detail"] for v in violations]
        validation_flags.extend(missing_data_flags)

        high_severity = any(v.get("severity") == "high" for v in violations)
        has_missing_data = bool(missing_data_flags)
        decision = (
            "FLAGGED" if high_severity or has_missing_data else "APPROVED"
        )
        confidence = 0.85 if not violations and not has_missing_data else 0.50

        if validation_flags:
            logger.warning(f"[E1] Validation flags: {validation_flags}")
        logger.info(
            f"[E1] Decision: {decision} (confidence={confidence:.2f}), "
            f"total={total_price:,.2f} {currency}, "
            f"missing_data_flags={len(missing_data_flags)}"
        )

        # ── Step 8: Write to State ───────────────────────
        state.commercial_result = CommercialResult(
            decision=decision,
            total_price=total_price,
            currency=currency,
            line_items=line_items,
            risk_margin_pct=0.0,
            payment_schedule=payment_schedule,
            assumptions=assumptions,
            exclusions=exclusions,
            commercial_narrative=full_narrative,
            validation_flags=validation_flags,
            confidence=confidence,
        )
        state.status = PipelineStatus.COMMERCIAL_LEGAL_REVIEW
        return state

    # ── Helpers ──────────────────────────────────────────

    def _analyse_scope(
        self, state: RFPGraphState,
    ) -> tuple[dict[str, int], int]:
        """Count requirements by category."""
        reqs = (
            state.requirements_validation.validated_requirements
            or state.requirements
        )
        counter: Counter[str] = Counter()
        for req in reqs:
            cat = (
                req.category.value
                if hasattr(req.category, "value")
                else str(req.category)
            )
            counter[cat] += 1
        return dict(counter), sum(counter.values())

    def _extract_rfp_commercial_context(
        self,
        mcp: MCPService,
        rfp_id: str,
        state: RFPGraphState,
    ) -> str:
        """Extract pricing/commercial guidelines and requirements from the RFP."""
        queries = [
            "pricing guidelines budget commercial terms",
            "payment schedule milestones financial",
            "cost breakdown pricing structure",
            "subscriber count users scale scope",
            "project timeline duration implementation phases",
        ]
        all_texts: list[str] = []
        seen: set[str] = set()

        try:
            result_sets = mcp.query_rfp_batch(queries, rfp_id, top_k=5)
            for query, results in zip(queries, result_sets):
                for r in results:
                    text = r.get("text", "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        all_texts.append(text)
        except Exception as exc:
            logger.warning(f"[E1] Batched RFP pricing query failed: {exc}")
            for query in queries:
                try:
                    results = mcp.query_rfp(query, rfp_id, top_k=5)
                    for r in results:
                        text = r.get("text", "").strip()
                        if text and text not in seen:
                            seen.add(text)
                            all_texts.append(text)
                except Exception as inner_exc:
                    logger.warning(
                        f"[E1] RFP query failed for '{query}': {inner_exc}"
                    )

        # Also include any commercial-category requirements
        reqs = (
            state.requirements_validation.validated_requirements
            or state.requirements
        )
        for req in reqs:
            cat = (
                req.category.value
                if hasattr(req.category, "value")
                else str(req.category)
            )
            if cat.upper() in ("COMMERCIAL", "FINANCIAL", "PRICING"):
                text = req.text.strip()
                if text and text not in seen:
                    seen.add(text)
                    all_texts.append(f"[COMMERCIAL REQ] {text}")

        return "\n\n".join(all_texts) if all_texts else "No commercial context found in the RFP."

    def _extract_rfp_pricing_layout(
        self,
        mcp: MCPService,
        rfp_id: str,
    ) -> str:
        """Detect the RFP's expected pricing table column layout."""
        queries = [
            "pricing table format columns schedule line item",
            "pricing schedule cost breakdown table structure",
            "price schedule NRC MRC unit cost columns",
            "commercial response format pricing template",
        ]
        layout_texts: list[str] = []
        seen: set[str] = set()

        try:
            result_sets = mcp.query_rfp_batch(queries, rfp_id, top_k=3)
            for query, results in zip(queries, result_sets):
                for r in results:
                    text = r.get("text", "").strip()
                    if text and text not in seen:
                        if "|" in text or re.search(
                            r'\b(?:Line\s*#|Item\s*Description|NRC|MRC|Unit\s*(?:Rate|Cost)|Total\s*(?:Cost|Price))\b',
                            text, re.IGNORECASE
                        ):
                            seen.add(text)
                            layout_texts.append(text)
        except Exception as exc:
            logger.warning(f"[E1] Batched pricing-layout query failed: {exc}")
            for query in queries:
                try:
                    results = mcp.query_rfp(query, rfp_id, top_k=3)
                    for r in results:
                        text = r.get("text", "").strip()
                        if text and text not in seen:
                            if "|" in text or re.search(
                                r'\b(?:Line\s*#|Item\s*Description|NRC|MRC|Unit\s*(?:Rate|Cost)|Total\s*(?:Cost|Price))\b',
                                text, re.IGNORECASE
                            ):
                                seen.add(text)
                                layout_texts.append(text)
                except Exception as inner_exc:
                    logger.warning(
                        f"[E1] Pricing layout query failed for '{query}': {inner_exc}"
                    )

        if layout_texts:
            logger.info(
                f"[E1] Detected RFP pricing layout ({len(layout_texts)} fragments)"
            )
        return "\n\n".join(layout_texts) if layout_texts else ""

    def _query_kb_pricing(self, mcp: MCPService) -> str:
        """Query the knowledge base for product pricing catalog,
        rate cards, and commercial terms."""
        queries = [
            "product pricing catalog rates modules",
            "per subscriber pricing tiers rate card",
            "implementation cost estimates professional services",
            "managed services AMS pricing operations",
            "licensing fees software subscription costs",
            "payment terms commercial conditions",
        ]

        all_texts: list[str] = []
        seen: set[str] = set()

        try:
            result_sets = mcp.query_knowledge_batch(queries, top_k=5)
            for query, results in zip(queries, result_sets):
                for r in results:
                    text = r.get("text", "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        all_texts.append(text)
        except Exception as exc:
            logger.warning(f"[E1] Batched KB pricing query failed: {exc}")
            for query in queries:
                try:
                    results = mcp.query_knowledge(query, top_k=5)
                    for r in results:
                        text = r.get("text", "").strip()
                        if text and text not in seen:
                            seen.add(text)
                            all_texts.append(text)
                except Exception as inner_exc:
                    logger.warning(
                        f"[E1] KB pricing query failed for '{query}': {inner_exc}"
                    )

        return "\n\n".join(all_texts) if all_texts else "NO PRICING DATA FOUND IN KNOWLEDGE BASE."

    def _build_requirements_detail(self, state: RFPGraphState) -> str:
        """Build a compact requirement summary for the LLM prompt."""
        reqs = (
            state.requirements_validation.validated_requirements
            or state.requirements
        )
        lines = []
        for req in reqs[:50]:  # cap at 50 to stay within token budget
            cat = (
                req.category.value
                if hasattr(req.category, "value")
                else str(req.category)
            )
            text = req.text[:200]
            lines.append(f"- [{cat}] {text}")
        return "\n".join(lines) if lines else "No requirements available."

    def _llm_commercial_analysis(
        self,
        state: RFPGraphState,
        req_counts: dict[str, int],
        total_reqs: int,
        rfp_commercial_context: str,
        kb_pricing_data: str,
        requirements_detail: str,
        rfp_pricing_layout: str = "",
    ) -> dict[str, Any]:
        """Send context to LLM and get structured commercial analysis."""
        template = _PROMPT_PATH.read_text(encoding="utf-8")

        # Build requirement breakdown
        breakdown = "\n".join(
            f"  - {cat}: {count} requirements"
            for cat, count in req_counts.items()
        )

        prompt = (
            template
            .replace("{client_name}", state.rfp_metadata.client_name or "the Client")
            .replace("{rfp_title}", state.rfp_metadata.rfp_title or "RFP Response")
            .replace("{total_requirements}", str(total_reqs))
            .replace("{requirement_breakdown}", breakdown)
            .replace("{requirements_detail}", self._truncate_at_word(requirements_detail, 4000))
            .replace("{rfp_commercial_context}", self._truncate_at_word(rfp_commercial_context, 4000))
            .replace("{kb_pricing_data}", self._truncate_at_word(kb_pricing_data, 5000))
        )

        # Inject RFP pricing layout if detected
        if rfp_pricing_layout:
            pricing_layout_block = (
                "\n\n## RFP Pricing Table Layout (Detected)\n"
                "The RFP specifies the following pricing table structure. "
                "Your line_items and commercial_narrative MUST mirror this layout:\n\n"
                f"{rfp_pricing_layout[:2000]}\n"
            )
            prompt += pricing_layout_block

        logger.info(
            f"[E1] Calling LLM for commercial analysis ({len(prompt)} chars)"
        )
        raw = llm_large_text_call(prompt)
        logger.debug(f"[E1] LLM response ({len(raw)} chars)")

        return self._parse_llm_response(raw)

    def _parse_llm_response(self, raw: str) -> dict[str, Any]:
        """Parse the LLM JSON response."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        # Strip single-line JS style comments (// comment) common in LLM hallucinations before JSON parse
        cleaned = re.sub(r'//.*$', '', cleaned, flags=re.MULTILINE)

        data: dict[str, Any] | None = None
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if data is None:
            logger.warning("[E1] Failed to parse LLM response as JSON")
            data = {
                "commercial_narrative": raw,
                "executive_summary": "",
                "line_items": [],
                "total_price": 0.0,
                "currency": "USD",
                "payment_schedule": [],
                "assumptions": [],
                "exclusions": [],
                "missing_data_flags": [
                    "LLM response could not be parsed — manual review required"
                ],
            }

        # Normalize list values to strings
        for key in ("executive_summary", "commercial_narrative"):
            val = data.get(key, "")
            if isinstance(val, list):
                data[key] = "\n\n".join(str(p) for p in val)

        return data

    def _parse_line_items(
        self, raw_items: list[dict[str, Any]],
    ) -> list[PricingLineItem]:
        """Convert raw LLM line items to PricingLineItem objects."""
        items = []
        for i, item in enumerate(raw_items):
            try:
                items.append(PricingLineItem(
                    label=str(item.get("label", f"Item {i+1}")),
                    quantity=float(item.get("quantity", 1)),
                    unit=str(item.get("unit", "fixed")),
                    unit_rate=float(item.get("unit_rate", 0)),
                    total=float(item.get("total", 0)),
                    category=str(item.get("category", "general")),
                ))
            except (ValueError, TypeError) as exc:
                logger.warning(f"[E1] Skipping invalid line item {i}: {exc}")
        return items

    @staticmethod
    def _truncate_at_word(text: str, max_chars: int) -> str:
        """Truncate text at a word boundary, never mid-word."""
        if len(text) <= max_chars:
            return text
        cut = text.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        return text[:cut]
