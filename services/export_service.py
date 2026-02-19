import os
from datetime import datetime

def synthesize_document(requirements: list, rfp_id: str) -> str:
    """
    Minimal synthesize: create a simple text-based document and return local path.
    Replace with python-docx generation and S3 upload in production.
    """
    out_dir = os.environ.get("RFP_OUT_DIR", "/tmp")
    filename = f"rfp_response_{rfp_id}_{int(datetime.utcnow().timestamp())}.docx"
    path = os.path.join(out_dir, filename)
    lines = []
    lines.append(f"RFP Response for {rfp_id}\n")
    for r in requirements:
        lines.append(f"ID: {r.get('id')}")
        lines.append(f"Title: {r.get('title')}")
        lines.append(f"Draft: {r.get('draft')}\n")
    # write plain text to file (placeholder)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
