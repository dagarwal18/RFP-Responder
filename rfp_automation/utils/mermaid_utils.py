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
import json
import logging
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Render settings ──────────────────────────────────────
MERMAID_RENDER_ARGS = [
    "--width", "1400",
    "--backgroundColor", "white",
    # Keep the CLI theme broadly compatible; diagram-level init blocks can
    # still override styling with themeVariables for richer visuals.
    "--theme", "default",
]
_LOCAL_RENDER_TIMEOUT = 120
_PUPPETEER_CONFIG = {
    "headless": True,
    "timeout": 120000,
    "protocolTimeout": 120000,
    "args": [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--allow-file-access-from-files",
    ],
}
_FALLBACK_RENDERER = Path(__file__).resolve().with_name("mermaid_renderer_fallback.cjs")


@dataclass
class MermaidBlock:
    """Represents a single mermaid code block found in markdown."""
    raw_match: str       # The full ```mermaid ... ``` string
    code: str            # The mermaid source code inside the fences
    index: int           # Zero-based index of this block in the document


# ═══════════════════════════════════════════════════════════
#  Sanitize — fix common syntax issues before rendering
# ═══════════════════════════════════════════════════════════

# Matches unquoted node labels inside [] that contain special characters.
# Captures: the opening bracket-type char, the label text, the closing char.
# Example: A[Microsoft Sentinel (SIEM)] → A["Microsoft Sentinel (SIEM)"]
_LABEL_WITH_SPECIAL_RE = re.compile(
    r'(\[)'             # opening [
    r'([^\]"]*'         # label text that is NOT already quoted
    r'[(){}]'           # must contain at least one special char
    r'[^\]"]*)'         # rest of label
    r'(\])',            # closing ]
)
_GANTT_RANGE_RE = re.compile(
    r"^(?P<label>[^:]+?)\s*:\s*(?P<start>\d{4}-\d{2}-\d{2})\s*,\s*(?P<end>\d{4}-\d{2}-\d{2})\s*$"
)


def _sanitize_gantt_code(code: str) -> str:
    """Repair common invalid gantt syntax emitted by the writer."""
    lines = code.splitlines()
    diagram_idx = _diagram_start_index(lines)
    if diagram_idx is None or lines[diagram_idx].strip() != "gantt":
        return code

    sanitized: list[str] = []
    has_date_format = False
    task_counter = 1

    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if idx < diagram_idx:
            sanitized.append(raw_line.rstrip())
            continue
        if idx == diagram_idx:
            sanitized.append("gantt")
            continue
        if not stripped:
            continue
        if stripped.startswith("desc "):
            continue
        if stripped.startswith("dateFormat"):
            has_date_format = True
            sanitized.append("    dateFormat YYYY-MM-DD")
            continue

        match = _GANTT_RANGE_RE.match(stripped)
        if match:
            label = match.group("label").strip()
            sanitized.append(
                f"    {label} : task_{task_counter}, {match.group('start')}, {match.group('end')}"
            )
            task_counter += 1
            continue

        sanitized.append(raw_line.rstrip())

    if not has_date_format:
        sanitized.insert(1, "    dateFormat YYYY-MM-DD")

    return "\n".join(sanitized)


def _sanitize_mermaid_code(code: str) -> str:
    """Auto-quote Mermaid node labels containing special characters.

    Mermaid uses ``()`` for rounded nodes, ``{}`` for diamond nodes, etc.
    When these chars appear inside ``[...]`` labels (e.g. ``[SIEM (v2)]``),
    the parser breaks.  Wrapping in ``"..."`` tells Mermaid to treat the
    content as a literal string.

    Only modifies labels that are NOT already quoted.
    """
    def _quote_label(m: re.Match) -> str:
        open_br, label, close_br = m.group(1), m.group(2), m.group(3)
        # Don't double-quote if already quoted
        if label.startswith('"') and label.endswith('"'):
            return m.group(0)
        return f'{open_br}"{label}"{close_br}'

    code = _LABEL_WITH_SPECIAL_RE.sub(_quote_label, code)
    return _sanitize_gantt_code(code)


def _diagram_start_index(lines: list[str]) -> int | None:
    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("%%{"):
            continue
        return idx
    return None


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


def _find_node() -> str | None:
    return shutil.which("node")


def _find_cached_mermaid_runtime() -> tuple[Path, Path] | None:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return None

    npx_root = Path(local_app_data) / "npm-cache" / "_npx"
    try:
        root_exists = npx_root.exists()
    except OSError:
        return None
    if not root_exists:
        return None

    candidates: list[tuple[float, Path, Path]] = []
    try:
        paths = list(npx_root.glob("*/node_modules/@mermaid-js/mermaid-cli/dist/index.html"))
    except OSError:
        return None

    for html_path in paths:
        package_root = html_path.parent.parent
        node_modules_root = package_root.parent.parent
        puppeteer_root = node_modules_root / "puppeteer"
        try:
            if not puppeteer_root.exists():
                continue
            mtime = html_path.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, html_path, puppeteer_root))

    if not candidates:
        return None

    _, html_path, puppeteer_root = max(candidates, key=lambda item: item[0])
    return html_path, puppeteer_root


def _is_mermaid_timeout_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in (
            "navigation timeout",
            "timed out",
            "timeouterror",
            "timeouterror",
        )
    )


def _render_with_local_browser(
    *,
    mmd_path: Path,
    png_path: Path,
    background_color: str,
    width: int,
    timeout: int,
) -> Path | Exception:
    node_path = _find_node()
    runtime = _find_cached_mermaid_runtime()
    if not node_path or not runtime or not _FALLBACK_RENDERER.exists():
        return EnvironmentError("Local Mermaid browser fallback is unavailable")

    mermaid_html_path, puppeteer_root = runtime
    cmd = [
        node_path,
        str(_FALLBACK_RENDERER),
        str(puppeteer_root),
        str(mermaid_html_path),
        str(mmd_path),
        str(png_path),
        background_color,
        str(width),
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=max(timeout, _LOCAL_RENDER_TIMEOUT),
            shell=False,
        )
        if png_path.exists() and png_path.stat().st_size > 0:
            logger.info("[Mermaid] Rendered via local browser fallback: %s", png_path.name)
            return png_path
        return Exception("Local browser fallback did not produce an image")
    except subprocess.CalledProcessError as e:
        message = e.stderr.strip() or e.stdout.strip() or str(e)
        return Exception(f"local browser render failed: {message[:240]}")
    except subprocess.TimeoutExpired:
        return TimeoutError(
            f"Local Mermaid browser fallback timed out after {max(timeout, _LOCAL_RENDER_TIMEOUT)}s"
        )


def _validate_mermaid_syntax(block_code: str) -> str | None:
    """Quick validation of Mermaid code before rendering.

    Returns None if valid, or an error description if invalid.
    Catches common issues that cause mmdc to hang indefinitely.
    """
    stripped = block_code.strip()
    if not stripped:
        return "Empty mermaid block"

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    diagram_idx = _diagram_start_index(lines)
    if diagram_idx is None:
        return "Empty mermaid block"

    # Must start with a valid diagram type keyword
    valid_starts = (
        "graph ", "graph\n", "flowchart ", "flowchart\n",
        "sequenceDiagram", "classDiagram", "stateDiagram",
        "erDiagram", "gantt", "pie", "journey",
        "gitGraph", "mindmap", "timeline", "quadrantChart",
        "sankey", "xychart", "block-beta",
    )
    first_line = lines[diagram_idx]
    if not any(first_line.startswith(s) for s in valid_starts):
        return f"Invalid diagram type: '{first_line[:50]}'"

    remaining_lines = [
        line.strip()
        for line in lines[diagram_idx + 1 :]
        if line.strip()
    ]
    if not remaining_lines:
        return "Mermaid block has no body"

    if first_line.startswith(("graph", "flowchart")):
        if len(remaining_lines) < 2:
            return "Graph/flowchart block is too short"
        if not any(
            token in line
            for line in remaining_lines
            for token in ("-->", "-.->", "==>", "---")
        ):
            return "Graph/flowchart block has no links"
    elif first_line.startswith("sequenceDiagram") and len(remaining_lines) < 2:
        return "Sequence diagram block is too short"

    # Check for placeholder text that will break the parser
    placeholder_patterns = [
        "⚠", "[TBD", "[TODO", "[Insert", "**⚠",
        "[Requires Manual Input]",
    ]
    for pattern in placeholder_patterns:
        if pattern in block_code:
            return f"Contains placeholder text: '{pattern}'"

    return None  # valid


def render_block(
    block_code: str,
    output_dir: Path,
    timeout: int = 60,
) -> Path | Exception:
    """Render a single Mermaid block to a PNG image.

    Uses a SHA-256 content hash as the filename so identical diagrams
    are cached automatically (idempotent).

    Returns:
        Path to the rendered PNG on success, or an Exception on failure.
    """
    # ── Validate syntax before attempting to render ──
    validation_error = _validate_mermaid_syntax(block_code)
    if validation_error:
        err = ValueError(f"Mermaid syntax validation failed: {validation_error}")
        logger.warning(f"[Mermaid] {err}")
        return err

    output_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize code: auto-quote labels with special chars like (SIEM)
    block_code = _sanitize_mermaid_code(block_code)

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
    puppeteer_config_path = output_dir / f"diagram_{digest}.puppeteer.json"
    puppeteer_config_path.write_text(
        json.dumps(_PUPPETEER_CONFIG, ensure_ascii=True),
        encoding="utf-8",
    )

    # Build command — prefer global mmdc, fallback to npx
    mmdc_path = _find_mmdc()
    if mmdc_path:
        cmd = [mmdc_path]
    else:
        cmd = ["npx.cmd" if os.name == "nt" else "npx", "--yes", "@mermaid-js/mermaid-cli@10.8.0"]

    cmd.extend([
        "-i", str(mmd_path.absolute()),
        "-o", str(png_path.absolute()),
        "-p", str(puppeteer_config_path.absolute()),
        *MERMAID_RENDER_ARGS,
    ])

    try:
        subprocess.run(
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
        stderr = e.stderr.strip()
        if _is_mermaid_timeout_error(stderr):
            fallback = _render_with_local_browser(
                mmd_path=mmd_path,
                png_path=png_path,
                background_color="white",
                width=1400,
                timeout=timeout,
            )
            if isinstance(fallback, Path):
                return fallback
            if isinstance(fallback, Exception):
                err = Exception(
                    f"mmdc failed (exit {e.returncode}): {stderr[:160]} "
                    f"[fallback unavailable: {fallback}]"
                )
            else:
                err = Exception(f"mmdc failed (exit {e.returncode}): {stderr[:200]}")
        else:
            err = Exception(
                f"mmdc failed (exit {e.returncode}): {stderr[:200]}"
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
        fallback = _render_with_local_browser(
            mmd_path=mmd_path,
            png_path=png_path,
            background_color="white",
            width=1400,
            timeout=timeout,
        )
        if isinstance(fallback, Path):
            return fallback
        err = TimeoutError(
            f"Mermaid render timed out after {timeout}s"
            + (
                f"; local browser fallback unavailable ({fallback})"
                if isinstance(fallback, Exception)
                else ""
            )
        )
        logger.warning(f"[Mermaid] {err}")
        return err
    finally:
        # Clean up temp .mmd file
        try:
            mmd_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            puppeteer_config_path.unlink(missing_ok=True)
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
            alignment_class = _diagram_alignment_class(result)
            replacement = (
                f'\n<div class="diagram-block {alignment_class}">'
                f'<img src="{abs_path}" alt="Diagram {block.index + 1}" />'
                f"</div>\n"
            )
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


def _diagram_alignment_class(image_path: Path) -> str:
    dimensions = _png_dimensions(image_path)
    if not dimensions:
        return "diagram-landscape"
    width, height = dimensions
    return "diagram-portrait" if height > width * 1.1 else "diagram-landscape"


def _png_dimensions(image_path: Path) -> tuple[int, int] | None:
    try:
        with image_path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None

    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None

    try:
        width, height = struct.unpack(">II", header[16:24])
    except struct.error:
        return None
    return width, height


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
