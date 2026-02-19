"""
RFP Response Automation — Main Entry Point

Run the pipeline directly (CLI):
    python -m rfp_automation.main

Run as an API server (for the frontend):
    python -m rfp_automation.main --serve
    # or: uvicorn rfp_automation.api:app --reload --port 8000

Or import and run programmatically:
    from rfp_automation.main import run
    result = run("path/to/rfp.pdf")
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from rfp_automation.orchestration.graph import run_pipeline
from rfp_automation.utils.logger import setup_logging


def run(file_path: str = "") -> dict:
    """Run the full RFP pipeline and return the final state."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("  RFP RESPONSE AUTOMATION SYSTEM")
    logger.info(f"  Mode: MOCK | Started: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    final_state = run_pipeline(uploaded_file_path=file_path)

    # Print summary
    _print_summary(final_state)

    return final_state


def _print_summary(state: dict) -> None:
    """Print a human-readable summary of the pipeline result."""
    logger = logging.getLogger(__name__)

    rfp_meta = state.get("rfp_metadata", {})
    status = state.get("status", "UNKNOWN")
    go_no_go = state.get("go_no_go_result", {})
    requirements = state.get("requirements", [])
    validation = state.get("technical_validation", {})
    commercial = state.get("commercial_result", {})
    legal = state.get("legal_result", {})
    approval = state.get("approval_package", {})
    submission = state.get("submission_record", {})

    logger.info("")
    logger.info("-" * 60)
    logger.info("  PIPELINE RESULT SUMMARY")
    logger.info("-" * 60)
    logger.info(f"  RFP ID:         {rfp_meta.get('rfp_id', 'N/A')}")
    logger.info(f"  Client:         {rfp_meta.get('client_name', 'N/A')}")
    logger.info(f"  Title:          {rfp_meta.get('rfp_title', 'N/A')}")
    logger.info(f"  Final Status:   {status}")
    logger.info(f"  Go/No-Go:       {go_no_go.get('decision', 'N/A')}")
    logger.info(f"  Requirements:   {len(requirements)} extracted")
    logger.info(f"  Validation:     {validation.get('decision', 'N/A')}")
    logger.info(f"  Legal:          {legal.get('decision', 'N/A')}")
    logger.info(f"  Approval:       {approval.get('approval_decision', 'N/A')}")

    pricing = commercial.get("pricing", {})
    if pricing:
        logger.info(f"  Total Price:    ${pricing.get('total_price', 0):,.2f}")

    if submission.get("submitted_at"):
        logger.info(f"  Submitted At:   {submission['submitted_at']}")
        logger.info(f"  File Hash:      {submission.get('file_hash', 'N/A')[:16]}...")

    logger.info("-" * 60)

    # Audit trail summary
    audit = state.get("audit_trail", [])
    logger.info(f"\n  Audit Trail: {len(audit)} entries")
    for entry in audit:
        logger.info(
            f"    v{entry.get('state_version', '?')} | "
            f"{entry.get('agent', '?')} | "
            f"{entry.get('action', '?')} | "
            f"{entry.get('details', '')}"
        )
    logger.info("")


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the FastAPI server (for frontend communication)."""
    import uvicorn

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"Starting API server on {host}:{port}")
    uvicorn.run("rfp_automation.api:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        file_arg = sys.argv[1] if len(sys.argv) > 1 else ""
        run(file_arg)
