#!/usr/bin/env python3
"""Quality evaluator for generated RFP responses.

This CLI computes the KPIs defined in Documentation/quality_evaluation_framework.md
from a pipeline artifact (checkpoint JSON or API run/status JSON).
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECKPOINT_PRIORITY = [
    "f1_final_readiness.json",
    "h1_human_validation_prepare.json",
    "commercial_legal_parallel.json",
    "d1_technical_validation.json",
    "c3_narrative_assembly.json",
    "c2_requirement_writing.json",
    "b2_requirements_validation.json",
    "b1_requirements_extraction.json",
    "a3_go_no_go.json",
    "a2_structuring.json",
    "a1_intake.json",
]


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}, got {type(data).__name__}")
    return data


def _resolve_artifact(path: Path) -> tuple[dict[str, Any], Path]:
    if path.is_file():
        data = _load_json(path)
        if isinstance(data.get("result"), dict):
            return data["result"], path
        return data, path

    if path.is_dir():
        for candidate in CHECKPOINT_PRIORITY:
            cp = path / candidate
            if cp.exists():
                return _load_json(cp), cp
        raise FileNotFoundError(
            f"No known checkpoint JSON found in {path}. Expected one of: {', '.join(CHECKPOINT_PRIORITY)}"
        )

    raise FileNotFoundError(f"Artifact path does not exist: {path}")


def _coverage_metrics(state: dict[str, Any]) -> dict[str, Any]:
    requirements = state.get("requirements") or []
    coverage_matrix = (state.get("writing_result") or {}).get("coverage_matrix") or []

    total_requirements = len(requirements)
    by_id = {}
    for entry in coverage_matrix:
        req_id = entry.get("requirement_id")
        if req_id:
            by_id[req_id] = entry

    full = 0
    partial = 0
    missing = 0
    for req in requirements:
        req_id = req.get("requirement_id")
        quality = (by_id.get(req_id) or {}).get("coverage_quality", "missing")
        if quality == "full":
            full += 1
        elif quality == "partial":
            partial += 1
        else:
            missing += 1

    critical_or_mandatory_missed = []
    for req in requirements:
        req_id = req.get("requirement_id")
        quality = (by_id.get(req_id) or {}).get("coverage_quality", "missing")
        is_mandatory = str(req.get("type", "")).upper() == "MANDATORY"
        is_critical = str(req.get("impact", "")).upper() == "CRITICAL"
        if quality == "missing" and (is_mandatory or is_critical):
            critical_or_mandatory_missed.append(req_id)

    coverage_pct = _pct(full, total_requirements)

    return {
        "name": "Requirement Coverage",
        "target_pct": 95.0,
        "total_requirements": total_requirements,
        "full": full,
        "partial": partial,
        "missing": missing,
        "coverage_pct": coverage_pct,
        "passes_target": coverage_pct >= 95.0 and not critical_or_mandatory_missed,
        "critical_or_mandatory_missed": [x for x in critical_or_mandatory_missed if x],
    }


def _groundedness_metrics(state: dict[str, Any]) -> dict[str, Any]:
    requirements = state.get("requirements") or []
    coverage_matrix = (state.get("writing_result") or {}).get("coverage_matrix") or []
    req_by_id = {r.get("requirement_id"): r for r in requirements if r.get("requirement_id")}

    addressed = {
        e.get("requirement_id")
        for e in coverage_matrix
        if e.get("requirement_id") and e.get("coverage_quality") in {"full", "partial"}
    }

    grounded = 0
    ungrounded_ids: list[str] = []
    for req_id in sorted(addressed):
        req = req_by_id.get(req_id) or {}
        chunk_indices = req.get("source_chunk_indices") or []
        table_idx = req.get("source_table_chunk_index", -1)
        source_section = str(req.get("source_section", "")).strip()

        has_citation = bool(chunk_indices) or (isinstance(table_idx, int) and table_idx >= 0) or bool(source_section)
        if has_citation:
            grounded += 1
        else:
            ungrounded_ids.append(req_id)

    total_claims = len(addressed)
    groundedness_pct = _pct(grounded, total_claims)
    hallucination_rate_pct = round(100.0 - groundedness_pct, 2) if total_claims > 0 else 0.0

    commercial = state.get("commercial_result") or {}
    line_items = commercial.get("line_items") or []
    total_price = _to_float(commercial.get("total_price"))
    pricing_fabrication_risk = bool(total_price and total_price > 0 and not line_items)

    return {
        "name": "Source Groundedness",
        "target_pct": 98.0,
        "claims_total": total_claims,
        "claims_with_valid_citations": grounded,
        "groundedness_pct": groundedness_pct,
        "hallucination_rate_pct": hallucination_rate_pct,
        "passes_target": groundedness_pct >= 98.0 and not pricing_fabrication_risk,
        "pricing_fabrication_risk": pricing_fabrication_risk,
        "ungrounded_requirement_ids": ungrounded_ids,
    }


def _numeric_metrics(state: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    commercial = state.get("commercial_result") or {}
    line_items = commercial.get("line_items") or []
    errors: list[str] = []

    numeric_points = 1
    running_total = 0.0

    for idx, item in enumerate(line_items, start=1):
        quantity = _to_float(item.get("quantity"))
        unit_rate = _to_float(item.get("unit_rate"))
        total = _to_float(item.get("total"))
        label = str(item.get("label", f"line_{idx}"))

        numeric_points += 3

        if quantity is None or unit_rate is None or total is None:
            errors.append(f"{label}: non-numeric quantity/unit_rate/total")
            continue

        expected = quantity * unit_rate
        tolerance = max(0.01, abs(expected) * 0.005)
        if abs(expected - total) > tolerance:
            errors.append(
                f"{label}: total mismatch (quantity*unit_rate={expected:.2f}, total={total:.2f})"
            )

        if quantity < 0 or unit_rate < 0 or total < 0:
            errors.append(f"{label}: negative commercial values")

        running_total += total

    declared_total = _to_float(commercial.get("total_price"))
    if declared_total is not None:
        tolerance = max(0.01, abs(running_total) * 0.005)
        if abs(running_total - declared_total) > tolerance:
            errors.append(
                f"Total mismatch (sum(line_items)={running_total:.2f}, total_price={declared_total:.2f})"
            )

    # Optional benchmark comparison for numeric values
    benchmark = gold.get("numeric_benchmark") or {}
    benchmark_errors = 0
    if benchmark:
        expected_total = _to_float(benchmark.get("expected_total_price"))
        if expected_total is not None and declared_total is not None:
            numeric_points += 1
            tolerance = max(0.01, abs(expected_total) * 0.01)
            if abs(expected_total - declared_total) > tolerance:
                benchmark_errors += 1
                errors.append(
                    f"Benchmark mismatch (expected_total={expected_total:.2f}, actual_total={declared_total:.2f})"
                )

    total_errors = len(errors)
    accuracy_pct = round(max(0.0, 100.0 - ((total_errors / max(1, numeric_points)) * 100.0)), 2)

    return {
        "name": "Numeric and Table Precision",
        "target_pct": 99.0,
        "numeric_points": numeric_points,
        "errors": errors,
        "error_count": total_errors,
        "numeric_accuracy_pct": accuracy_pct,
        "passes_target": accuracy_pct >= 99.0,
        "used_benchmark": bool(benchmark),
    }


def _compliance_metrics(state: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    legal = state.get("legal_result") or {}
    predicted = str(legal.get("decision", "")).upper() or "UNKNOWN"
    truth = str(gold.get("legal_ground_truth_decision", "")).upper()

    proxy_inconsistency_count = 0
    clause_risks = legal.get("clause_risks") or []
    block_reasons = legal.get("block_reasons") or []

    if predicted == "BLOCKED" and not block_reasons:
        proxy_inconsistency_count += 1
    if predicted == "APPROVED":
        for risk in clause_risks:
            risk_level = str(risk.get("risk_level", "")).upper()
            recommendation = str(risk.get("recommendation", "")).lower()
            if risk_level == "CRITICAL" or recommendation == "reject":
                proxy_inconsistency_count += 1
                break

    has_truth = truth in {"APPROVED", "BLOCKED", "CONDITIONAL"}

    if has_truth:
        is_positive_truth = truth == "BLOCKED"
        is_positive_pred = predicted == "BLOCKED"

        tp = int(is_positive_truth and is_positive_pred)
        fp = int((not is_positive_truth) and is_positive_pred)
        fn = int(is_positive_truth and (not is_positive_pred))
        tn = int((not is_positive_truth) and (not is_positive_pred))

        precision = _pct(tp, tp + fp)
        recall = _pct(tp, tp + fn)
        false_pass_rate = 100.0 if fn > 0 else 0.0
        false_block_rate = 100.0 if fp > 0 else 0.0
        compliance_score = 100.0 if predicted == truth else 0.0

        return {
            "name": "Policy and Compliance Safety",
            "target_false_pass_rate_pct": 0.0,
            "predicted_legal_decision": predicted,
            "ground_truth_legal_decision": truth,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision_pct": precision,
            "recall_pct": recall,
            "false_pass_rate_pct": false_pass_rate,
            "false_block_rate_pct": false_block_rate,
            "compliance_score_pct": compliance_score,
            "passes_target": math.isclose(false_pass_rate, 0.0),
            "mode": "ground_truth",
        }

    compliance_score = 100.0 if proxy_inconsistency_count == 0 else max(0.0, 100.0 - (proxy_inconsistency_count * 50.0))
    return {
        "name": "Policy and Compliance Safety",
        "target_false_pass_rate_pct": 0.0,
        "predicted_legal_decision": predicted,
        "ground_truth_legal_decision": None,
        "precision_pct": None,
        "recall_pct": None,
        "false_pass_rate_pct": None,
        "false_block_rate_pct": None,
        "compliance_score_pct": compliance_score,
        "passes_target": proxy_inconsistency_count == 0,
        "mode": "proxy",
        "proxy_inconsistency_count": proxy_inconsistency_count,
        "note": "Provide --gold file with legal_ground_truth_decision for strict FPR/FBR metrics.",
    }


def _human_acceptance_metrics(state: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    review = state.get("review_package") or {}
    response_sections = review.get("response_sections") or []
    comments = review.get("comments") or []
    decision = ((review.get("decision") or {}).get("decision") or "").upper()

    total_sections = len(response_sections)
    if total_sections == 0:
        total_sections = len((state.get("writing_result") or {}).get("section_responses") or [])

    gold_approved = gold.get("human_first_pass_sections_approved")
    if isinstance(gold_approved, int) and total_sections > 0:
        approved_first_pass = max(0, min(gold_approved, total_sections))
        source = "ground_truth"
    else:
        touched_sections = {
            ((c.get("anchor") or {}).get("section_id") or "")
            for c in comments
            if ((c.get("anchor") or {}).get("domain") == "response")
        }
        touched_count = len([x for x in touched_sections if x])
        if decision == "APPROVE" and int(review.get("open_comment_count", 0)) == 0:
            approved_first_pass = total_sections
        else:
            approved_first_pass = max(0, total_sections - touched_count)
        source = "proxy"

    rate_pct = _pct(approved_first_pass, total_sections)

    return {
        "name": "First-Pass Approval Rate",
        "target_pct": 80.0,
        "total_sections": total_sections,
        "approved_on_first_pass": approved_first_pass,
        "first_pass_approval_rate_pct": rate_pct,
        "passes_target": rate_pct >= 80.0,
        "evaluation_source": source,
    }


def _response_quality_score(
    coverage_pct: float,
    groundedness_pct: float,
    numeric_accuracy_pct: float,
    compliance_score_pct: float,
    first_pass_approval_pct: float,
) -> float:
    return round(
        (0.30 * coverage_pct)
        + (0.25 * groundedness_pct)
        + (0.20 * numeric_accuracy_pct)
        + (0.15 * compliance_score_pct)
        + (0.10 * first_pass_approval_pct),
        2,
    )


def evaluate(state: dict[str, Any], gold: dict[str, Any] | None = None) -> dict[str, Any]:
    gold = gold or {}

    coverage = _coverage_metrics(state)
    groundedness = _groundedness_metrics(state)
    numeric = _numeric_metrics(state, gold)
    compliance = _compliance_metrics(state, gold)
    human = _human_acceptance_metrics(state, gold)

    rqs = _response_quality_score(
        coverage_pct=coverage["coverage_pct"],
        groundedness_pct=groundedness["groundedness_pct"],
        numeric_accuracy_pct=numeric["numeric_accuracy_pct"],
        compliance_score_pct=float(compliance.get("compliance_score_pct") or 0.0),
        first_pass_approval_pct=human["first_pass_approval_rate_pct"],
    )

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "rfp_id": ((state.get("rfp_metadata") or {}).get("rfp_id") or state.get("tracking_rfp_id") or "unknown"),
        "metrics": {
            "requirement_coverage": coverage,
            "source_groundedness": groundedness,
            "numeric_precision": numeric,
            "policy_compliance_safety": compliance,
            "first_pass_approval": human,
        },
        "aggregate": {
            "response_quality_score_pct": rqs,
            "formula": "RQS = 0.30(Cov) + 0.25(Ground) + 0.20(Num) + 0.15(Comp) + 0.10(Approve)",
            "component_values_pct": {
                "Cov": coverage["coverage_pct"],
                "Ground": groundedness["groundedness_pct"],
                "Num": numeric["numeric_accuracy_pct"],
                "Comp": compliance.get("compliance_score_pct"),
                "Approve": human["first_pass_approval_rate_pct"],
            },
        },
    }


def _to_markdown(report: dict[str, Any], source_path: Path) -> str:
    m = report["metrics"]
    a = report["aggregate"]

    lines = [
        "# Response Quality Evaluation Report",
        "",
        f"- Source Artifact: `{source_path}`",
        f"- Evaluated At (UTC): `{report['evaluated_at']}`",
        f"- RFP ID: `{report['rfp_id']}`",
        "",
        "## KPI Summary",
        "",
        "| KPI | Score | Target | Pass |",
        "| :-- | --: | --: | :--: |",
        f"| Requirement Coverage | {m['requirement_coverage']['coverage_pct']}% | >= 95% | {'YES' if m['requirement_coverage']['passes_target'] else 'NO'} |",
        f"| Source Groundedness | {m['source_groundedness']['groundedness_pct']}% | >= 98% | {'YES' if m['source_groundedness']['passes_target'] else 'NO'} |",
        f"| Numeric and Table Precision | {m['numeric_precision']['numeric_accuracy_pct']}% | >= 99% | {'YES' if m['numeric_precision']['passes_target'] else 'NO'} |",
        f"| Policy and Compliance Safety | {m['policy_compliance_safety'].get('compliance_score_pct')}% | False Pass Rate = 0% | {'YES' if m['policy_compliance_safety']['passes_target'] else 'NO'} |",
        f"| First-Pass Approval Rate | {m['first_pass_approval']['first_pass_approval_rate_pct']}% | >= 80% | {'YES' if m['first_pass_approval']['passes_target'] else 'NO'} |",
        "",
        "## Aggregate",
        "",
        f"- Response Quality Score (RQS): **{a['response_quality_score_pct']}%**",
        f"- Formula: `{a['formula']}`",
        "",
        "## Key Details",
        "",
        f"- Critical/Mandatory missed requirements: {len(m['requirement_coverage']['critical_or_mandatory_missed'])}",
        f"- Ungrounded addressed requirements: {len(m['source_groundedness']['ungrounded_requirement_ids'])}",
        f"- Numeric errors found: {m['numeric_precision']['error_count']}",
        f"- Compliance mode: {m['policy_compliance_safety']['mode']}",
        f"- Human acceptance source: {m['first_pass_approval']['evaluation_source']}",
        "",
    ]

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate generated RFP response quality metrics.")
    parser.add_argument(
        "--artifact",
        required=True,
        help=(
            "Path to a run artifact JSON or checkpoint directory (for example: "
            "storage/checkpoints/<rfp_id>)."
        ),
    )
    parser.add_argument(
        "--gold",
        default="",
        help="Optional path to gold labels JSON for strict compliance/human/numeric benchmarking.",
    )
    parser.add_argument("--output-json", default="", help="Write full report JSON to this path.")
    parser.add_argument("--output-md", default="", help="Write markdown report to this path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    artifact_input = Path(args.artifact)
    state, resolved_path = _resolve_artifact(artifact_input)

    gold_data: dict[str, Any] = {}
    if args.gold:
        gold_data = _load_json(Path(args.gold))

    report = evaluate(state, gold_data)

    print("\n=== RFP Response Quality Evaluation ===")
    print(f"Artifact: {resolved_path}")
    print(f"RFP ID: {report['rfp_id']}")
    print(f"RQS: {report['aggregate']['response_quality_score_pct']}%")

    metrics = report["metrics"]
    print(f"Coverage: {metrics['requirement_coverage']['coverage_pct']}%")
    print(f"Groundedness: {metrics['source_groundedness']['groundedness_pct']}%")
    print(f"Numeric Accuracy: {metrics['numeric_precision']['numeric_accuracy_pct']}%")
    print(f"Compliance Score: {metrics['policy_compliance_safety'].get('compliance_score_pct')}%")
    print(f"First-Pass Approval: {metrics['first_pass_approval']['first_pass_approval_rate_pct']}%")

    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote JSON report: {output_json}")

    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(_to_markdown(report, resolved_path), encoding="utf-8")
        print(f"Wrote Markdown report: {output_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
