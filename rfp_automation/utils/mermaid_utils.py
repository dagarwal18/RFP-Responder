"""
Mermaid diagram utilities — extract, render, and rewrite.

Provides:
  - extract_mermaid_blocks()  → find all ```mermaid blocks in markdown
  - render_block()            → render a single block to PNG via mmdc (cached)
  - rewrite_markdown()        → replace blocks with image links or error fallbacks
  - process_mermaid_blocks()  → convenience wrapper for the full pipeline
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Render settings ──────────────────────────────────────
MERMAID_RENDER_ARGS = [
    "--width", "1200",
    "--backgroundColor", "white",
    "--theme", "default",
]


@dataclass
class MermaidBlock:
    """Represents a single mermaid code block found in markdown."""
    raw_match: str       # The full ```mermaid ... ``` string
    code: str            # The mermaid source code inside the fences
    index: int           # Zero-based index of this block in the document


# ═══════════════════════════════════════════════════════════
#  Extract
# ═══════════════════════════════════════════════════════════

_MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def extract_mermaid_blocks(markdown: str) -> list[MermaidBlock]:
    """Find all ```mermaid ... ``` code blocks in the given markdown."""
    blocks: list[MermaidBlock] = []
    for i, match in enumerate(_MERMAID_RE.finditer(markdown)):
        blocks.append(MermaidBlock(
            raw_match=match.group(0),
            code=match.group(1).strip(),
            index=i,
        ))
    return blocks


# ═══════════════════════════════════════════════════════════
#  Render (single block → PNG via mmdc, with SHA-256 caching)
# ═══════════════════════════════════════════════════════════

def _find_mmdc() -> str | None:
    """Check if mmdc (mermaid-cli) is available on PATH."""
    return shutil.which("mmdc")


def render_block(
    block_code: str,
    output_dir: Path,
    timeout: int = 30,
) -> Path | Exception:
    """Render a single Mermaid block to a PNG image.

    Uses a SHA-256 content hash as the filename so identical diagrams
    are cached automatically (idempotent).

    Returns:
        Path to the rendered PNG on success, or an Exception on failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Content-addressed filename for free caching
    digest = hashlib.sha256(block_code.encode("utf-8")).hexdigest()[:12]
    png_path = output_dir / f"diagram_{digest}.png"

    # Cache hit — skip rendering
    if png_path.exists() and png_path.stat().st_size > 0:
        logger.info(f"[Mermaid] Cache hit: {png_path.name}")
        return png_path

    # Write temporary .mmd file
    mmd_path = output_dir / f"diagram_{digest}.mmd"
    mmd_path.write_text(block_code, encoding="utf-8")

    # Build command — prefer global mmdc, fallback to npx
    mmdc_path = _find_mmdc()
    if mmdc_path:
        cmd = [mmdc_path]
    else:
        cmd = ["npx", "--yes", "@mermaid-js/mermaid-cli@10.8.0"]

    cmd.extend([
        "-i", str(mmd_path.absolute()),
        "-o", str(png_path.absolute()),
        *MERMAID_RENDER_ARGS,
    ])

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=(os.name == "nt"),
        )
        logger.info(f"[Mermaid] Rendered: {png_path.name}")
        return png_path
    except subprocess.CalledProcessError as e:
        err = Exception(
            f"mmdc failed (exit {e.returncode}): {e.stderr.strip()[:200]}"
        )
        logger.warning(f"[Mermaid] Render failed for diagram_{digest}: {err}")
        return err
    except FileNotFoundError:
        err = EnvironmentError(
            "mermaid-cli (mmdc) not found. Install with: "
            "npm install -g @mermaid-js/mermaid-cli@10.x"
        )
        logger.error(f"[Mermaid] {err}")
        return err
    except subprocess.TimeoutExpired:
        err = TimeoutError(f"Mermaid render timed out after {timeout}s")
        logger.warning(f"[Mermaid] {err}")
        return err
    finally:
        # Clean up temp .mmd file
        try:
            mmd_path.unlink(missing_ok=True)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════
#  Rewrite (replace blocks with image links or error notes)
# ═══════════════════════════════════════════════════════════

def rewrite_markdown(
    markdown: str,
    rendered_map: dict[int, Path | Exception],
) -> str:
    """Replace mermaid blocks with image links or styled error fallbacks.

    Args:
        markdown:     The original markdown string.
        rendered_map: Mapping from block index → rendered PNG path or Exception.

    Returns:
        The modified markdown string.
    """
    blocks = extract_mermaid_blocks(markdown)
    if not blocks:
        return markdown

    for block in reversed(blocks):  # reverse to preserve indices
        result = rendered_map.get(block.index)
        if isinstance(result, Path):
            # Use absolute path so xhtml2pdf resolves it correctly
            abs_path = str(result.absolute()).replace("\\", "/")
            replacement = f"![Diagram {block.index + 1}]({abs_path})"
        elif isinstance(result, Exception):
            # Graceful fallback: show the error as a blockquote
            replacement = (
                f"\n> **⚠ Diagram render failed:** {result}\n"
                f">\n> ```\n> {block.code[:300]}\n> ```\n"
            )
        else:
            # No result for this block (shouldn't happen, but be safe)
            replacement = (
                f"\n> *[Diagram {block.index + 1} not rendered]*\n"
            )
        markdown = markdown.replace(block.raw_match, replacement, 1)

    return markdown


# ═══════════════════════════════════════════════════════════
#  Convenience wrapper
# ═══════════════════════════════════════════════════════════

def process_mermaid_blocks(markdown: str, diagrams_dir: Path) -> str:
    """Extract, render, and rewrite all mermaid blocks in one call.

    Args:
        markdown:     The full proposal markdown.
        diagrams_dir: Directory to save rendered PNGs.

    Returns:
        The modified markdown with image links replacing mermaid blocks.
    """
    blocks = extract_mermaid_blocks(markdown)
    if not blocks:
        logger.info("[Mermaid] No mermaid blocks found — skipping.")
        return markdown

    logger.info(f"[Mermaid] Found {len(blocks)} diagram(s) to render.")

    rendered_map: dict[int, Path | Exception] = {}
    for block in blocks:
        rendered_map[block.index] = render_block(block.code, diagrams_dir)

    success = sum(1 for v in rendered_map.values() if isinstance(v, Path))
    failed = len(rendered_map) - success
    logger.info(
        f"[Mermaid] Rendering complete: {success} succeeded, {failed} failed."
    )

    return rewrite_markdown(markdown, rendered_map)
