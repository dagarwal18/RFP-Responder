"""
Vision Service — DETR table detection + Groq VLM structured extraction.

Two-stage pipeline:
  1. Microsoft Table Transformer (DETR) detects table bounding boxes locally
  2. Groq VLM (Qwen3 32B) extracts structured table data from cropped regions

Also supports:
  • Diagram/figure description via VLM

No new API keys needed — uses the existing groq_api_key.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from typing import Any

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────

_TABLE_EXTRACTION_PROMPT = """Extract ALL tables from this image as structured data.
For each table, return a JSON object:
{"table_id": "T1", "caption": "brief caption if visible", "headers": ["Col1", "Col2"], "rows": [["val1", "val2"]]}
Return a JSON array of table objects. If no tables, return [].
Return ONLY the JSON array, no other text."""

_DIAGRAM_DESCRIPTION_PROMPT = """Describe any diagrams, flowcharts, or figures visible in this image.
Include all labels, arrows, relationships, and visible text.
If no diagrams are present, return "NO_DIAGRAM"."""


# ═══════════════════════════════════════════════════════════
# DETR Table Detector (local model)
# ═══════════════════════════════════════════════════════════

class TableDetector:
    """
    Detect table bounding boxes using Microsoft's Table Transformer (DETR).

    Model: microsoft/table-transformer-detection
    Runs locally — no API key needed.
    """

    _instance: TableDetector | None = None
    _model = None
    _processor = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_model(self) -> None:
        """Lazy-load the DETR model on first use."""
        if self._model is not None:
            return

        try:
            from transformers import AutoImageProcessor, TableTransformerForObjectDetection

            logger.info("[TableDetector] Loading microsoft/table-transformer-detection ...")
            self._processor = AutoImageProcessor.from_pretrained(
                "microsoft/table-transformer-detection"
            )
            self._model = TableTransformerForObjectDetection.from_pretrained(
                "microsoft/table-transformer-detection"
            )
            logger.info("[TableDetector] Model loaded successfully")
        except Exception as e:
            logger.error(f"[TableDetector] Failed to load DETR model: {e}")
            raise

    def detect_tables(
        self,
        page_image_bytes: bytes,
        confidence_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Detect table regions in a page image.

        Returns list of dicts: {bbox: [x1, y1, x2, y2], confidence: float}
        Coordinates are in pixel space of the input image.
        """
        import torch
        from PIL import Image

        self._load_model()

        image = Image.open(io.BytesIO(page_image_bytes)).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")

        with torch.no_grad():
            outputs = self._model(**inputs)

        # Post-process: convert to absolute bounding boxes
        target_size = torch.tensor([image.size[::-1]])  # (height, width)
        results = self._processor.post_process_object_detection(
            outputs, threshold=confidence_threshold, target_sizes=target_size
        )[0]

        detections: list[dict[str, Any]] = []
        for score, bbox in zip(results["scores"], results["boxes"]):
            detections.append({
                "bbox": [round(c.item(), 1) for c in bbox],  # [x1, y1, x2, y2]
                "confidence": round(score.item(), 3),
            })

        logger.info(
            f"[TableDetector] Detected {len(detections)} table(s) "
            f"(threshold={confidence_threshold})"
        )
        return detections


# ═══════════════════════════════════════════════════════════
# VLM Service (Groq API)
# ═══════════════════════════════════════════════════════════

class VisionService:
    """
    Extract structured data from document images via Groq VLM.

    Uses DETR for table detection, then Groq VLM for content extraction.
    """

    def __init__(self):
        self._settings = get_settings()
        self._table_detector = TableDetector()

    # ── Public API ───────────────────────────────────────

    def extract_tables_from_page(
        self,
        page_image_bytes: bytes,
        page_number: int,
    ) -> list[dict[str, Any]]:
        """
        Detect and extract tables from a page image.

        Pipeline: DETR detection → crop regions → VLM extraction.
        Returns list of structured table dicts:
          {table_id, caption, headers, rows}
        """
        from PIL import Image

        # Step 1: Detect table bounding boxes with DETR
        try:
            detections = self._table_detector.detect_tables(page_image_bytes)
        except Exception as e:
            logger.warning(f"[VisionService] DETR detection failed on page {page_number}: {e}")
            return []

        if not detections:
            logger.debug(f"[VisionService] No tables detected on page {page_number}")
            return []

        # Step 2: Crop each table region and send to VLM
        image = Image.open(io.BytesIO(page_image_bytes)).convert("RGB")
        all_tables: list[dict[str, Any]] = []

        for idx, det in enumerate(detections):
            bbox = det["bbox"]  # [x1, y1, x2, y2]

            # Add small padding around the detected region
            pad = 10
            x1 = max(0, bbox[0] - pad)
            y1 = max(0, bbox[1] - pad)
            x2 = min(image.width, bbox[2] + pad)
            y2 = min(image.height, bbox[3] + pad)

            cropped = image.crop((x1, y1, x2, y2))

            # Convert cropped image to bytes
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            cropped_bytes = buf.getvalue()

            logger.debug(
                f"[VisionService] Sending table region {idx + 1}/{len(detections)} "
                f"to VLM (page {page_number}, bbox={bbox})"
            )

            try:
                vlm_response = self._call_vlm(cropped_bytes, _TABLE_EXTRACTION_PROMPT)
                tables = self._parse_table_json(vlm_response, page_number, idx)
                all_tables.extend(tables)
            except Exception as e:
                logger.warning(
                    f"[VisionService] VLM extraction failed for table region "
                    f"{idx + 1} on page {page_number}: {e}"
                )

        logger.info(
            f"[VisionService] Extracted {len(all_tables)} table(s) from page {page_number}"
        )
        return all_tables

    def extract_diagram_description(
        self,
        image_bytes: bytes,
        page_number: int,
    ) -> str:
        """
        Describe diagrams/figures in an image region via VLM.

        Returns natural language description, or empty string if
        no diagram is found or VLM fails.
        """
        try:
            response = self._call_vlm(image_bytes, _DIAGRAM_DESCRIPTION_PROMPT)
            if response.strip().upper() == "NO_DIAGRAM":
                return ""
            return response.strip()
        except Exception as e:
            logger.warning(
                f"[VisionService] Diagram description failed on page {page_number}: {e}"
            )
            return ""

    # ── VLM API call ─────────────────────────────────────

    def _call_vlm(
        self,
        image_bytes: bytes,
        prompt: str,
        max_retries: int = 3,
    ) -> str:
        """
        Send an image + prompt to Groq VLM API and return the text response.

        Uses direct HTTP to Groq's OpenAI-compatible endpoint.
        """
        import requests

        if not self._settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is not set — required for VLM calls")

        # Base64-encode the image
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": self._settings.vlm_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_image}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": self._settings.vlm_max_tokens,
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {self._settings.groq_api_key}",
            "Content-Type": "application/json",
        }

        url = "https://api.groq.com/openai/v1/chat/completions"

        for attempt in range(1, max_retries + 1):
            try:
                t0 = time.perf_counter()
                resp = requests.post(url, json=payload, headers=headers, timeout=60)
                elapsed = time.perf_counter() - t0

                if resp.status_code == 429:
                    # Rate limited — back off
                    wait = min(2 ** attempt, 10)
                    logger.warning(
                        f"[VLM] Rate limited (attempt {attempt}/{max_retries}), "
                        f"waiting {wait}s"
                    )
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                logger.info(
                    f"[VLM] Response in {elapsed:.2f}s | "
                    f"len={len(content)} chars | model={self._settings.vlm_model}"
                )
                return content

            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"[VLM] Request failed (attempt {attempt}/{max_retries}): {e}"
                )
                if attempt < max_retries:
                    time.sleep(1.0 * attempt)

        raise RuntimeError(f"VLM call failed after {max_retries} attempts")

    # ── JSON parsing helpers ─────────────────────────────

    @staticmethod
    def _parse_table_json(
        vlm_response: str,
        page_number: int,
        region_idx: int,
    ) -> list[dict[str, Any]]:
        """Parse VLM JSON response into structured table dicts."""
        # Strip markdown code fences if present
        text = vlm_response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines[1:] if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            tables = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(
                f"[VisionService] Failed to parse VLM JSON for page {page_number} "
                f"region {region_idx}: {e}"
            )
            return []

        if not isinstance(tables, list):
            tables = [tables]

        # Validate and normalize each table
        valid_tables: list[dict[str, Any]] = []
        for i, tbl in enumerate(tables):
            if not isinstance(tbl, dict):
                continue

            valid_tables.append({
                "table_id": tbl.get("table_id", f"T{region_idx + 1}_{i + 1}"),
                "caption": tbl.get("caption", ""),
                "headers": tbl.get("headers", []),
                "rows": tbl.get("rows", []),
                "page_number": page_number,
            })

        return valid_tables

    @staticmethod
    def format_table_as_text(table: dict[str, Any]) -> str:
        """
        Format a structured table dict as pipe-delimited text.

        Output:
          Header1 | Header2 | Header3
          val1 | val2 | val3
          ...
        """
        lines: list[str] = []

        headers = table.get("headers", [])
        if headers:
            lines.append(" | ".join(str(h) for h in headers))

        for row in table.get("rows", []):
            if isinstance(row, list):
                lines.append(" | ".join(str(cell) for cell in row))

        return "\n".join(lines) if lines else ""
