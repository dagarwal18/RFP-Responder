"""
Knowledge Loader — utility to seed company knowledge into Pinecone + MongoDB.

Usage:
    python -m rfp_automation.mcp.knowledge_loader          # seed all
    python -m rfp_automation.mcp.knowledge_loader --type capabilities
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rfp_automation.config import get_settings
from rfp_automation.mcp.vector_store.knowledge_store import KnowledgeStore

logger = logging.getLogger(__name__)

# Default path to seed data (relative to this file)
_DATA_DIR = Path(__file__).parent / "knowledge_data"


def _load_json(filename: str) -> Any:
    """Read a JSON file from the knowledge_data directory."""
    path = _DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_capabilities(store: KnowledgeStore) -> int:
    """Seed company capabilities into Pinecone knowledge namespace."""
    caps = _load_json("capabilities.json")
    texts = [
        f"{c['name']}: {c['description']} Evidence: {c.get('evidence', '')}"
        for c in caps
    ]
    metadatas = [
        {
            "id": c["id"],
            "name": c["name"],
            "category": c.get("category", ""),
            "tags": ",".join(c.get("tags", [])),
        }
        for c in caps
    ]
    return store.ingest_company_docs(texts, metadatas, doc_type="capability")


def seed_past_proposals(store: KnowledgeStore) -> int:
    """Seed past winning proposals into Pinecone knowledge namespace."""
    proposals = _load_json("past_proposals.json")
    texts = [
        f"{p['title']}: {p['excerpt']} Outcome: {p.get('outcome', '')}"
        for p in proposals
    ]
    metadatas = [
        {
            "id": p["id"],
            "title": p["title"],
            "category": p.get("category", ""),
            "tags": ",".join(p.get("tags", [])),
        }
        for p in proposals
    ]
    return store.ingest_company_docs(texts, metadatas, doc_type="past_proposal")


def seed_certifications_to_mongo(store: KnowledgeStore) -> None:
    """Seed certification holdings into MongoDB company_config."""
    certs = _load_json("certifications.json")
    db = store._get_db()
    db.company_config.update_one(
        {"config_type": "certifications"},
        {"$set": {"config_type": "certifications", "certifications": certs}},
        upsert=True,
    )
    held = sum(1 for v in certs.values() if v)
    logger.info(f"Seeded {len(certs)} certifications ({held} held) into MongoDB")


def seed_pricing_rules_to_mongo(store: KnowledgeStore) -> None:
    """Seed pricing rules into MongoDB company_config."""
    rules = _load_json("pricing_rules.json")
    db = store._get_db()
    db.company_config.update_one(
        {"config_type": "pricing_rules"},
        {"$set": {"config_type": "pricing_rules", "rules": rules}},
        upsert=True,
    )
    logger.info("Seeded pricing rules into MongoDB")


def seed_legal_templates_to_mongo(store: KnowledgeStore) -> None:
    """Seed legal templates into MongoDB company_config."""
    templates = _load_json("legal_templates.json")
    db = store._get_db()
    db.company_config.update_one(
        {"config_type": "legal_templates"},
        {"$set": {"config_type": "legal_templates", "templates": templates}},
        upsert=True,
    )
    logger.info(f"Seeded {len(templates)} legal templates into MongoDB")


def seed_all() -> dict[str, int | str]:
    """Run all seed operations. Returns a summary dict."""
    store = KnowledgeStore()
    results: dict[str, int | str] = {}

    logger.info("═" * 50)
    logger.info("  SEEDING COMPANY KNOWLEDGE")
    logger.info("═" * 50)

    # Pinecone vectors
    results["capabilities"] = seed_capabilities(store)
    results["past_proposals"] = seed_past_proposals(store)

    # MongoDB structured data
    seed_certifications_to_mongo(store)
    results["certifications"] = "seeded"

    seed_pricing_rules_to_mongo(store)
    results["pricing_rules"] = "seeded"

    seed_legal_templates_to_mongo(store)
    results["legal_templates"] = "seeded"

    logger.info(f"Seed results: {results}")
    return results


# ── CLI entry point ──────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="Seed company knowledge")
    parser.add_argument(
        "--type",
        choices=["capabilities", "proposals", "certifications", "pricing", "legal", "all"],
        default="all",
        help="Which data to seed (default: all)",
    )
    args = parser.parse_args()

    store = KnowledgeStore()

    if args.type == "all":
        seed_all()
    elif args.type == "capabilities":
        seed_capabilities(store)
    elif args.type == "proposals":
        seed_past_proposals(store)
    elif args.type == "certifications":
        seed_certifications_to_mongo(store)
    elif args.type == "pricing":
        seed_pricing_rules_to_mongo(store)
    elif args.type == "legal":
        seed_legal_templates_to_mongo(store)

    print("Done.")
