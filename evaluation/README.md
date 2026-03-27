# Quality Evaluation Toolkit

This folder contains standalone evaluation code to score generated RFP responses against the KPIs defined in `Documentation/quality_evaluation_framework.md`.

## What This Evaluates

The evaluator computes all core framework metrics:

1. Requirement Coverage
2. Source Groundedness (anti-hallucination)
3. Numeric and Table Precision
4. Policy and Compliance Safety
5. First-Pass Approval Rate
6. Aggregate Response Quality Score (RQS)

## Inputs Supported

You can evaluate from:

- A checkpoint directory: `storage/checkpoints/<rfp_id>/`
- A single checkpoint JSON file (for example `f1_final_readiness.json`)
- An API run/status JSON containing top-level `result`

## Quick Start

```bash
python evaluation/evaluate_response.py \
  --artifact storage/checkpoints/<rfp_id> \
  --output-json evaluation/reports/<rfp_id>_quality.json \
  --output-md evaluation/reports/<rfp_id>_quality.md
```

## Strict Ground-Truth Mode (Recommended)

Provide a gold labels file to compute strict compliance quality (including FPR/FBR) and optional numeric/human benchmarks:

```bash
python evaluation/evaluate_response.py \
  --artifact storage/checkpoints/<rfp_id> \
  --gold evaluation/examples/gold_labels.example.json \
  --output-json evaluation/reports/<rfp_id>_quality.json
```

Without a gold file, the evaluator uses proxy logic for legal/compliance and human acceptance where exact ground truth is unavailable.

## Gold Labels JSON Schema

```json
{
  "legal_ground_truth_decision": "BLOCKED",
  "human_first_pass_sections_approved": 8,
  "numeric_benchmark": {
    "expected_total_price": 1250000.0
  }
}
```

## Output

The script prints summary KPIs and can write:

- Full JSON report (`--output-json`)
- Human-readable markdown report (`--output-md`)

## Notes

- Targets are aligned to the framework document:
  - Coverage >= 95%
  - Groundedness >= 98%
  - Numeric Accuracy >= 99%
  - Compliance target: False Pass Rate = 0%
  - First-Pass Approval >= 80%
- RQS formula:
  - `RQS = 0.30(Cov) + 0.25(Ground) + 0.20(Num) + 0.15(Comp) + 0.10(Approve)`
