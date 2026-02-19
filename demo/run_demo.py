"""Runnable demo that simulates the project's architecture and workflow.

Run with: python demo/run_demo.py

This script is intentionally self-contained so it can be run without
installing or wiring the rest of the repository. It demonstrates the
high-level flow: ingest -> extract -> validate -> reason (CBR) ->
persistence -> export.
"""
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import json


@dataclass
class Document:
    id: str
    text: str


def ingest() -> Document:
    text = (
        "We need a system that can assess vendor proposals. "
        "Vendor X proposes cloud hosting with 99.9% SLA and annual security audits."
    )
    return Document(id="doc-1", text=text)


def extract(doc: Document) -> Dict[str, Any]:
    # Simple keyword-based extractor to demonstrate behavior
    claims = []
    if "99.9%" in doc.text:
        claims.append({"claim": "SLA:99.9%", "confidence": 0.9})
    if "security audits" in doc.text:
        claims.append({"claim": "security-audits:annual", "confidence": 0.8})
    return {"doc_id": doc.id, "claims": claims}


def validate(extracted: Dict[str, Any]) -> Dict[str, Any]:
    # Example validator that enforces minimum confidence
    validated = []
    for c in extracted["claims"]:
        if c.get("confidence", 0) >= 0.75:
            validated.append({**c, "valid": True})
        else:
            validated.append({**c, "valid": False})
    return {"doc_id": extracted["doc_id"], "validated_claims": validated}


def cbr_reasoning(validated: Dict[str, Any]) -> Dict[str, Any]:
    # Very small Case-Based Reasoning stub: match validated claims to decisions
    decisions = []
    for c in validated["validated_claims"]:
        if c["valid"]:
            if c["claim"].startswith("SLA"):
                decisions.append({"decision": "accept-with-conditions", "reason": c["claim"]})
            else:
                decisions.append({"decision": "accept", "reason": c["claim"]})
        else:
            decisions.append({"decision": "review", "reason": c["claim"]})
    return {"doc_id": validated["doc_id"], "decisions": decisions}


def persist(result: Dict[str, Any]) -> str:
    # Persist to a local JSON file as a stand-in for DB
    path = f"demo_output_{result['document']['id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return path


def export(path: str) -> None:
    # Simulate exporting by printing the persisted file location
    print(f"Exported result saved to: {path}")


def run() -> None:
    print("--- Demo run starting ---")
    doc = ingest()
    print("Ingested document:", doc.id)

    extracted = extract(doc)
    print("Extracted claims:", extracted["claims"])

    validated = validate(extracted)
    print("Validated claims:", validated["validated_claims"])

    decisions = cbr_reasoning(validated)
    print("Decisions:", decisions["decisions"])

    # Combine results to persist
    result = {
        "document": asdict(doc),
        "extracted": extracted,
        "validated": validated,
        "decisions": decisions["decisions"],
    }

    path = persist(result)
    export(path)
    print("--- Demo run complete ---")


if __name__ == "__main__":
    run()
