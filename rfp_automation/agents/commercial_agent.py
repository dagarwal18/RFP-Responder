"""
E1 — Commercial Agent
Responsibility: Generate pricing breakdown using deterministic Python math
                from pricing_rules.json, then call LLM for narrative prose.
                Runs in parallel with E2 Legal.

Processing Flow:
  1. Scope Analysis — count requirements by category, estimate complexity
  2. MCP Query — load pricing rules configuration
  3. Deterministic Pricing — pure-Python formula (no LLM for math)
  4. LLM Narrative — generate commercial prose via llm_large_text_call
  5. Validation — commercial_rules.py checks margins/caps/discounts
  6. Write CommercialResult to state
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
        complexity_multiplier = self._compute_complexity(state)
        logger.info(
            f"[E1] Scope: {total_reqs} requirements across "
            f"{len(req_counts)} categories, complexity={complexity_multiplier:.2f}"
        )

        # ── Step 2: Load Pricing Config ──────────────────
        pricing_config = mcp.commercial_rules.load_pricing_config()
        currency = pricing_config.get("currency", "USD")

        # Also try MCP knowledge for enrichment
        pricing_kb = mcp.query_knowledge("pricing rules payment terms", top_k=3)
        logger.debug(
            f"[E1] Pricing config loaded. KB enrichment: {len(pricing_kb)} results"
        )

        # ── Step 3: Deterministic Pricing ────────────────
        line_items, subtotal = self._compute_pricing(
            req_counts, complexity_multiplier, pricing_config,
        )
        risk_margin_pct = pricing_config.get("risk_margin_percent", 0.10)
        risk_amount = subtotal * risk_margin_pct
        total_price = subtotal + risk_amount

        logger.info(
            f"[E1] Pricing: subtotal=${subtotal:,.2f}, "
            f"risk_margin={risk_margin_pct:.0%} (${risk_amount:,.2f}), "
            f"total=${total_price:,.2f} {currency}"
        )

        # ── Step 4: LLM Narrative ────────────────────────
        commercial_narrative = ""
        payment_schedule: list[dict] = []
        assumptions: list[str] = []
        exclusions: list[str] = []

        try:
            narrative_data = self._generate_narrative(
                state, line_items, total_price, currency,
                req_counts, risk_margin_pct,
            )
            commercial_narrative = narrative_data.get("commercial_narrative", "")
            payment_schedule = narrative_data.get("payment_schedule", [])
            assumptions = narrative_data.get("assumptions", [])
            exclusions = narrative_data.get("exclusions", [])

            # Prepend executive summary to the narrative
            exec_summary = narrative_data.get("executive_summary", "")
            if exec_summary and commercial_narrative:
                commercial_narrative = (
                    f"## Executive Pricing Summary\n\n{exec_summary}\n\n"
                    f"## Commercial Terms\n\n{commercial_narrative}"
                )
        except Exception as exc:
            logger.warning(f"[E1] LLM narrative generation failed: {exc}")
            commercial_narrative = (
                f"Total proposed investment: ${total_price:,.2f} {currency}. "
                "Detailed commercial terms to be provided upon request."
            )

        # ── Step 5: Validation ───────────────────────────
        violations = mcp.commercial_rules.validate_pricing(
            total_price=total_price,
            total_cost=0.0,  # cost not tracked yet
            discount_percent=0.0,
        )
        validation_flags = [v["detail"] for v in violations]
        high_severity = any(v.get("severity") == "high" for v in violations)

        decision = "FLAGGED" if high_severity else "APPROVED"
        confidence = 0.85 if not violations else 0.60

        if validation_flags:
            logger.warning(f"[E1] Validation flags: {validation_flags}")
        logger.info(f"[E1] Decision: {decision} (confidence={confidence:.2f})")

        # ── Step 6: Write to State ───────────────────────
        state.commercial_result = CommercialResult(
            decision=decision,
            total_price=total_price,
            currency=currency,
            line_items=line_items,
            risk_margin_pct=risk_margin_pct * 100,  # store as percentage
            payment_schedule=payment_schedule,
            assumptions=assumptions,
            exclusions=exclusions,
            commercial_narrative=commercial_narrative,
            validation_flags=validation_flags,
            confidence=confidence,
        )
        state.status = PipelineStatus.COMMERCIAL_LEGAL_REVIEW

        return state

    # ── Helpers ──────────────────────────────────────────

    def _analyse_scope(
        self, state: RFPGraphState,
    ) -> tuple[dict[str, int], int]:
        """Count requirements by category. Uses validated requirements
        if available, otherwise raw requirements."""
        reqs = (
            state.requirements_validation.validated_requirements
            or state.requirements
        )
        counter: Counter[str] = Counter()
        for req in reqs:
            cat = req.category.value if hasattr(req.category, "value") else str(req.category)
            counter[cat] += 1
        return dict(counter), sum(counter.values())

    def _compute_complexity(self, state: RFPGraphState) -> float:
        """Derive complexity multiplier from coverage matrix.
        Sections with partial coverage get a 1.2× uplift."""
        matrix = state.writing_result.coverage_matrix
        if not matrix:
            return 1.0

        total = len(matrix)
        partial = sum(
            1 for entry in matrix if entry.coverage_quality == "partial"
        )
        missing = sum(
            1 for entry in matrix if entry.coverage_quality == "missing"
        )
        if total == 0:
            return 1.0

        # Weighted: partial=1.2, missing=1.5, full=1.0
        score = ((total - partial - missing) * 1.0 + partial * 1.2 + missing * 1.5) / total
        return round(score, 2)

    def _compute_pricing(
        self,
        req_counts: dict[str, int],
        complexity_multiplier: float,
        config: dict[str, Any],
    ) -> tuple[list[PricingLineItem], float]:
        """Deterministic pricing formula. Returns (line_items, subtotal)."""
        base_fee = config.get("base_cost", 50_000.0)
        per_req_rate = config.get("per_requirement_cost", 2_000.0)
        complexity_tiers = config.get("complexity_tiers", {})

        line_items: list[PricingLineItem] = []

        # Base fee line item
        line_items.append(PricingLineItem(
            label="Base Implementation Fee",
            quantity=1,
            unit="fixed",
            unit_rate=base_fee,
            total=base_fee,
            category="base",
        ))

        # Per-category line items
        category_tier_map = {
            "TECHNICAL": "high",
            "SECURITY": "high",
            "COMPLIANCE": "medium",
            "FUNCTIONAL": "medium",
            "COMMERCIAL": "low",
            "OPERATIONAL": "medium",
        }

        for category, count in req_counts.items():
            tier = category_tier_map.get(category.upper(), "medium")
            tier_multiplier = complexity_tiers.get(tier, 1.0)
            line_total = count * per_req_rate * tier_multiplier * complexity_multiplier

            line_items.append(PricingLineItem(
                label=f"{category.title()} Requirements",
                quantity=float(count),
                unit="requirements",
                unit_rate=round(per_req_rate * tier_multiplier * complexity_multiplier, 2),
                total=round(line_total, 2),
                category=category,
            ))

        subtotal = sum(item.total for item in line_items)
        return line_items, round(subtotal, 2)

    def _generate_narrative(
        self,
        state: RFPGraphState,
        line_items: list[PricingLineItem],
        total_price: float,
        currency: str,
        req_counts: dict[str, int],
        risk_margin_pct: float,
    ) -> dict[str, Any]:
        """Call LLM to generate commercial narrative prose."""
        # Build line items text
        line_items_text = "\n".join(
            f"  - {item.label}: {item.quantity:.0f} {item.unit} × "
            f"${item.unit_rate:,.2f} = ${item.total:,.2f}"
            for item in line_items
        )

        # Build requirement breakdown
        breakdown = "\n".join(
            f"  - {cat}: {count} requirements"
            for cat, count in req_counts.items()
        )

        # Load prompt template
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        prompt = (
            template
            .replace("{client_name}", state.rfp_metadata.client_name or "the Client")
            .replace("{rfp_title}", state.rfp_metadata.rfp_title or "RFP Response")
            .replace("{proposal_word_count}", str(state.assembled_proposal.word_count))
            .replace("{currency}", currency)
            .replace("{requirement_breakdown}", breakdown)
            .replace("{total_price}", f"${total_price:,.2f}")
            .replace("{line_items_text}", line_items_text)
            .replace("{risk_margin_pct}", f"{risk_margin_pct * 100:.1f}")
        )

        logger.info(f"[E1] Calling LLM for commercial narrative ({len(prompt)} chars)")
        raw = llm_large_text_call(prompt)
        logger.debug(f"[E1] LLM narrative response ({len(raw)} chars)")

        return self._parse_narrative_response(raw)

    def _parse_narrative_response(self, raw: str) -> dict[str, Any]:
        """Parse the LLM JSON response for narrative data."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON block
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        logger.warning("[E1] Failed to parse LLM narrative response as JSON")
        # Return the raw text as the narrative
        return {
            "commercial_narrative": raw,
            "executive_summary": "",
            "payment_schedule": [],
            "assumptions": [],
            "exclusions": [],
        }
