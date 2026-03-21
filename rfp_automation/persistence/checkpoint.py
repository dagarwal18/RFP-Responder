"""
Checkpoint — file-based per-agent state persistence.

Saves pipeline state after each agent completes, allowing:
  • Pipeline state to survive uvicorn --reload
  • Re-running individual agents using cached predecessor state
  • Inspecting intermediate state for debugging

Storage: storage/checkpoints/{rfp_id}/{agent_name}.json
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CHECKPOINT_ROOT = Path("./storage/checkpoints")

# Ordered list of agent nodes in the pipeline
AGENT_ORDER: list[str] = [
    "a1_intake",
    "a2_structuring",
    "a3_go_no_go",
    "b1_requirements_extraction",
    "b2_requirements_validation",
    "c1_architecture_planning",
    "c2_requirement_writing",
    "c3_narrative_assembly",
    "d1_technical_validation",
    "commercial_legal_parallel",
    "h1_human_validation_prepare",
    "f1_final_readiness",
]


def _checkpoint_dir(rfp_id: str) -> Path:
    """Return the checkpoint directory for a given RFP."""
    return _CHECKPOINT_ROOT / rfp_id


def _state_to_serializable(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable types."""
    if isinstance(obj, Enum):
        return obj.value  # "MANDATORY", "GO", etc.
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return _state_to_serializable(obj.model_dump())
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return {k: _state_to_serializable(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, dict):
        return {k: _state_to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_state_to_serializable(item) for item in obj]
    if isinstance(obj, (set, frozenset)):
        return [_state_to_serializable(item) for item in obj]
    return obj


def save_checkpoint(rfp_id: str, agent_name: str, state_dict: dict[str, Any]) -> Path:
    """
    Save pipeline state after an agent completes.
    Returns the path to the checkpoint file.
    """
    checkpoint_dir = _checkpoint_dir(rfp_id)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    filepath = checkpoint_dir / f"{agent_name}.json"
    serializable = _state_to_serializable(state_dict)
    serializable["_checkpoint"] = {
        "agent": agent_name,
        "rfp_id": rfp_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, default=str)

    logger.info(f"💾 Checkpoint saved: {agent_name} → {filepath}")
    return filepath


def load_checkpoint(rfp_id: str, agent_name: str) -> dict[str, Any] | None:
    """
    Load a specific agent's checkpoint.
    Returns None if checkpoint doesn't exist.
    """
    filepath = _checkpoint_dir(rfp_id) / f"{agent_name}.json"
    if not filepath.exists():
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info(f"📂 Checkpoint loaded: {agent_name} ← {filepath}")
    return data


def get_predecessor(agent_name: str) -> str | None:
    """Return the agent that runs immediately before the given one."""
    try:
        idx = AGENT_ORDER.index(agent_name)
        return AGENT_ORDER[idx - 1] if idx > 0 else None
    except ValueError:
        return None


def load_checkpoint_up_to(rfp_id: str, start_from: str) -> dict[str, Any] | None:
    """
    Load the checkpoint from the agent immediately before `start_from`.
    This gives us the state needed to begin execution at `start_from`.
    """
    predecessor = get_predecessor(start_from)
    if predecessor is None:
        logger.warning(f"No predecessor for {start_from} — must start from scratch")
        return None
    return load_checkpoint(rfp_id, predecessor)


def list_checkpoints(rfp_id: str) -> list[dict[str, Any]]:
    """
    List all available checkpoints for an RFP, ordered by pipeline position.
    Returns list of {agent, saved_at, file_size_bytes}.
    """
    checkpoint_dir = _checkpoint_dir(rfp_id)
    if not checkpoint_dir.exists():
        return []

    result = []
    for agent_name in AGENT_ORDER:
        filepath = checkpoint_dir / f"{agent_name}.json"
        if filepath.exists():
            stat = filepath.stat()
            result.append({
                "agent": agent_name,
                "saved_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "file_size_bytes": stat.st_size,
            })
    return result


def clear_checkpoints(rfp_id: str) -> int:
    """
    Delete all checkpoints for an RFP.
    Returns the number of files deleted.
    """
    checkpoint_dir = _checkpoint_dir(rfp_id)
    if not checkpoint_dir.exists():
        return 0

    count = sum(1 for f in checkpoint_dir.iterdir() if f.is_file())
    shutil.rmtree(checkpoint_dir)
    logger.info(f"🗑️  Cleared {count} checkpoints for {rfp_id}")
    return count


def find_rfp_by_file_hash(file_hash: str) -> str | None:
    """
    Scan checkpoint directories to find an RFP that matches a file hash.
    Checks the a1_intake checkpoint for a matching file_hash field.
    Returns the rfp_id if found, None otherwise.
    """
    if not _CHECKPOINT_ROOT.exists():
        return None

    for rfp_dir in _CHECKPOINT_ROOT.iterdir():
        if not rfp_dir.is_dir():
            continue
        intake_file = rfp_dir / "a1_intake.json"
        if intake_file.exists():
            try:
                with open(intake_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                stored_hash = data.get("file_hash", "")
                if stored_hash == file_hash:
                    return rfp_dir.name
            except (json.JSONDecodeError, OSError):
                continue
    return None


def load_latest_checkpoint(rfp_id: str) -> dict[str, Any] | None:
    """
    Load the most recent checkpoint for an RFP.

    Walks AGENT_ORDER in reverse and returns the first (= latest pipeline
    stage) checkpoint file that exists.  Returns None when no checkpoints
    are found.
    """
    for agent_name in reversed(AGENT_ORDER):
        data = load_checkpoint(rfp_id, agent_name)
        if data is not None:
            return data
    return None


def discover_all_rfps() -> list[str]:
    """
    Return every rfp_id that has at least one checkpoint directory on disk.
    """
    if not _CHECKPOINT_ROOT.exists():
        return []
    return [
        d.name
        for d in sorted(_CHECKPOINT_ROOT.iterdir())
        if d.is_dir()
    ]


# ═══════════════════════════════════════════════════════════
#  Pipeline Log Collector — captures WARNING+ to file
# ═══════════════════════════════════════════════════════════

class PipelineLogCollector(logging.Handler):
    """Logging handler that collects WARNING+ records during a pipeline run.

    After the run, `flush_to_file()` writes all collected records to
    ``storage/checkpoints/{rfp_id}/pipeline_errors.log``.
    """

    def __init__(self, rfp_id: str, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self.rfp_id = rfp_id
        self._records: list[logging.LogRecord] = []
        self.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)

    def flush_to_file(self) -> Path | None:
        """Write collected records to disk and clear the buffer."""
        if not self._records:
            logger.info("No warnings or errors captured during this run.")
            return None

        checkpoint_dir = _checkpoint_dir(self.rfp_id)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        log_path = checkpoint_dir / "pipeline_errors.log"

        with open(log_path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"\n{'=' * 70}\n")
            f.write(f"Pipeline Run — {datetime.now().isoformat()} — RFP: {self.rfp_id}\n")
            f.write(f"Total records: {len(self._records)}\n")
            f.write("=" * 70 + "\n\n")
            for record in self._records:
                f.write(self.format(record) + "\n")

        logger.info(
            f"📋 Pipeline error log written: {len(self._records)} record(s) → {log_path}"
        )
        self._records.clear()
        return log_path


# Singleton reference for the active collector
_active_collector: PipelineLogCollector | None = None


def start_log_capture(rfp_id: str) -> None:
    """Attach a PipelineLogCollector to the root logger."""
    global _active_collector
    stop_log_capture()  # clean up any previous collector

    _active_collector = PipelineLogCollector(rfp_id)
    logging.getLogger().addHandler(_active_collector)
    logger.info(f"📋 Pipeline log capture started for {rfp_id}")


def stop_log_capture() -> Path | None:
    """Detach the collector, write to file, and return the log path."""
    global _active_collector
    if _active_collector is None:
        return None

    log_path = _active_collector.flush_to_file()
    logging.getLogger().removeHandler(_active_collector)
    _active_collector = None
    return log_path
