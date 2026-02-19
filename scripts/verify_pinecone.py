"""
Pinecone Verification Script
=============================
Inspects the Pinecone index to verify that vectors are stored correctly.

Usage:
    python scripts/verify_pinecone.py                  # full inspection
    python scripts/verify_pinecone.py --query "security requirements"
    python scripts/verify_pinecone.py --namespace RFP-ABC12345
    python scripts/verify_pinecone.py --query "cloud migration" --namespace RFP-ABC12345

Run from the project root.
"""

from __future__ import annotations

import argparse
import sys
import os
import inspect

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rfp_automation.config import get_settings

HR = "-" * 60
HR2 = "=" * 60


def _trunc(text: str, n: int = 120) -> str:
    return (text[:n] + "...") if len(text) > n else text


def _attr(obj, key, default=None):
    """Get attribute from either dict or object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def verify_index(args: argparse.Namespace) -> None:
    settings = get_settings()

    print()
    print(HR2)
    print("  PINECONE VERIFICATION")
    print(HR2)
    print(f"  Index name  : {settings.pinecone_index_name}")
    print(f"  Cloud/Region: {settings.pinecone_cloud} / {settings.pinecone_region}")
    if len(settings.pinecone_api_key) > 4:
        print(f"  API key     : ****...{settings.pinecone_api_key[-4:]}")
    else:
        print("  API key     : (not set)")
    print(HR2)

    # 1. Connect
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=settings.pinecone_api_key)
    except Exception as e:
        print(f"\n[ERROR] Failed to connect to Pinecone: {e}")
        return

    # 2. List indexes
    indexes = [idx.name for idx in pc.list_indexes()]
    print(f"\nAvailable indexes: {indexes}")

    if settings.pinecone_index_name not in indexes:
        print(f"\n[WARN] Index '{settings.pinecone_index_name}' does NOT exist yet.")
        print("  This is expected if no documents have been ingested.")
        return

    index = pc.Index(settings.pinecone_index_name)

    # 3. Index statistics
    print(f"\n{HR}")
    print("  INDEX STATISTICS")
    print(HR)

    stats = index.describe_index_stats()
    total = _attr(stats, "total_vector_count", 0)
    dimension = _attr(stats, "dimension", "?")
    namespaces_raw = _attr(stats, "namespaces", {})

    # Normalize namespaces to dict[str, dict]
    namespaces: dict = {}
    if isinstance(namespaces_raw, dict):
        for k, v in namespaces_raw.items():
            if isinstance(v, dict):
                namespaces[k] = v
            else:
                namespaces[k] = {"vector_count": _attr(v, "vector_count", 0)}
    elif hasattr(namespaces_raw, "__iter__"):
        for item in namespaces_raw:
            name = _attr(item, "name", str(item))
            namespaces[name] = {"vector_count": _attr(item, "vector_count", 0)}

    print(f"  Total vectors : {total:,}")
    print(f"  Dimension     : {dimension}")
    print(f"  Namespaces    : {len(namespaces)}")

    if namespaces:
        print()
        print(f"  {'Namespace':<40} {'Vectors':>8}")
        print(f"  {'-'*40} {'-'*8}")
        for ns_name in sorted(namespaces.keys()):
            ns_info = namespaces[ns_name]
            count = ns_info.get("vector_count", 0) if isinstance(ns_info, dict) else _attr(ns_info, "vector_count", 0)
            print(f"  {ns_name:<40} {count:>8,}")
    else:
        print("\n  (no namespaces -- index is empty)")

    if total == 0:
        print("\n[WARN] No vectors stored. Run the Intake Agent or knowledge loader first.")
        _check_data_flow()
        return

    # 4. Pick namespace
    target_ns = args.namespace
    if not target_ns and namespaces:
        target_ns = next(
            (ns for ns in sorted(namespaces.keys())),
            None,
        )

    # 5. Fetch sample vectors
    if target_ns:
        print(f"\n{HR}")
        print(f"  SAMPLE VECTORS  (namespace: {target_ns})")
        print(HR)

        try:
            listed = index.list(namespace=target_ns)
            vector_ids = []

            # Pinecone v5 list() yields pages — each page is a list of IDs.
            # Flatten all pages into a single list, then take the first 5.
            if hasattr(listed, "vectors"):
                vector_ids = [_attr(v, "id", str(v)) for v in listed.vectors]
            elif isinstance(listed, dict) and "vectors" in listed:
                vector_ids = [v["id"] for v in listed["vectors"]]
            elif hasattr(listed, "__iter__"):
                for item in listed:
                    if isinstance(item, str):
                        vector_ids.append(item)
                    elif isinstance(item, list):
                        # Page of IDs — flatten
                        vector_ids.extend(item)
                    elif hasattr(item, "id"):
                        vector_ids.append(item.id)
                    elif hasattr(item, "__iter__") and not isinstance(item, (str, bytes)):
                        # Iterable page (e.g. tuple)
                        vector_ids.extend(str(x) for x in item)
                    else:
                        vector_ids.append(str(item))
            vector_ids = vector_ids[:5]

            if vector_ids:
                print(f"  Sample IDs: {vector_ids}")
                fetched = index.fetch(ids=vector_ids, namespace=target_ns)
                vecs = _attr(fetched, "vectors", {})

                for vid in vector_ids:
                    vdata = vecs.get(vid) if isinstance(vecs, dict) else _attr(vecs, vid, None)
                    if vdata is None:
                        print(f"\n  [{vid}] -- not found in fetch")
                        continue

                    values = _attr(vdata, "values", [])
                    meta = _attr(vdata, "metadata", {})

                    print(f"\n  Vector: {vid}")
                    print(f"    dims={len(values)}  first_5={values[:5]}")

                    if meta:
                        meta_dict = meta if isinstance(meta, dict) else vars(meta)
                        for k, v in meta_dict.items():
                            val = _trunc(str(v), 100) if k == "text" else _trunc(str(v), 80)
                            print(f"    {k}: {val}")
            else:
                print("  (no vector IDs returned from list -- will verify via query)")
        except Exception as e:
            print(f"  [WARN] Could not list/fetch: {e}")
            print("  Will try query instead.")

    # 6. Query test
    query_text = args.query or "project requirements and deliverables"
    print(f"\n{HR}")
    print(f"  QUERY TEST")
    print(f"  Query: \"{query_text}\"")
    if target_ns:
        print(f"  Namespace: {target_ns}")
    print(HR)

    try:
        from rfp_automation.mcp.embeddings.embedding_model import EmbeddingModel
        embedder = EmbeddingModel()
        query_emb = embedder.embed_single(query_text)

        results = index.query(
            vector=query_emb,
            top_k=args.top_k,
            namespace=target_ns or "",
            include_metadata=True,
        )

        matches = _attr(results, "matches", [])
        if not matches:
            print("\n  [WARN] No matches returned.")
        else:
            print(f"\n  {len(matches)} results:\n")
            for i, m in enumerate(matches, 1):
                mid = _attr(m, "id", "?")
                score = _attr(m, "score", 0.0)
                meta = _attr(m, "metadata", {})
                meta_dict = meta if isinstance(meta, dict) else (vars(meta) if meta else {})
                text = meta_dict.get("text", "")

                print(f"  {i}. [{score:.4f}] {mid}")
                if text:
                    print(f"     text: {_trunc(text, 150)}")
                for k, v in meta_dict.items():
                    if k != "text":
                        print(f"     {k}: {_trunc(str(v), 80)}")
                print()
    except Exception as e:
        print(f"\n  [ERROR] Query failed: {e}")
        import traceback
        traceback.print_exc()

    # 7. Data flow check
    _check_data_flow()

    print(f"\n{HR2}")
    print("  VERIFICATION COMPLETE")
    print(f"{HR2}\n")


def _check_data_flow():
    """Check if store_rfp_chunks is implemented or still a stub."""
    print(f"\n{HR}")
    print("  DATA FLOW CHECK")
    print(HR)

    try:
        from rfp_automation.mcp.mcp_server import MCPService
        source = inspect.getsource(MCPService.store_rfp_chunks)
        if "TODO" in source:
            print("  [WARN] MCPService.store_rfp_chunks() is still a TODO stub.")
            print("    Structured chunks from the Intake Agent are logged but NOT")
            print("    persisted to Pinecone or MongoDB.")
            print()
            print("  Options to actually store data:")
            print("    1. Use store_rfp_document(rfp_id, raw_text) to embed raw text")
            print("    2. Implement store_rfp_chunks() to persist structured chunks")
        else:
            print("  [OK] MCPService.store_rfp_chunks() is implemented.")
    except Exception as e:
        print(f"  [ERROR] Could not inspect store_rfp_chunks: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Pinecone storage")
    parser.add_argument("--query", "-q", default="", help="Test query text")
    parser.add_argument("--namespace", "-n", default="", help="Target namespace")
    parser.add_argument("--top-k", "-k", type=int, default=5, help="Query results (default: 5)")
    args = parser.parse_args()
    verify_index(args)
