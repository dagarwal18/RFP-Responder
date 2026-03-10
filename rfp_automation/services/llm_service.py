"""
LLM Service — centralized Groq Cloud LLM client with multi-key round-robin.

All agents use this module to make LLM calls. Provides:
  - get_llm()              → returns configured Groq ChatModel (rotated key)
  - llm_json_call()        → structured output (parsed into Pydantic model)
  - llm_text_call()        → raw text response
  - llm_deterministic_call → deterministic (temp=0) text response
  - LLMCallTracker         → per-agent call count & timing stats
  - KeyRotator             → round-robin API key selection with TPM throttling
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Type, TypeVar

from pydantic import BaseModel

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Regex to strip Qwen3's <think>...</think> reasoning blocks from responses.
# Uses DOTALL so the pattern matches multi-line thinking content.
_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks that Qwen3 models emit before
    the actual answer.  Returns cleaned text with leading whitespace trimmed."""
    cleaned = _THINK_TAG_RE.sub("", text)
    return cleaned.strip()


# ═══════════════════════════════════════════════════════════
#  Key Rotator — round-robin across multiple Groq API keys
# ═══════════════════════════════════════════════════════════

class KeyRotator:
    """Round-robin API key selector with per-key TPM-aware throttling.

    The free Groq tier allows ~6K tokens/min per key.  By spacing
    calls at least ``min_gap_seconds`` apart *per key*, we stay safely
    under the TPM ceiling.  With N keys the effective gap is N×shorter.
    """

    _instance: KeyRotator | None = None
    _lock = threading.Lock()

    def __init__(self, keys: list[str], min_gap_seconds: float = 10.0) -> None:
        self._keys = keys
        self._idx = 0
        self._min_gap = min_gap_seconds
        # Track last-call timestamp per key index
        self._last_call: dict[int, float] = {}
        self._rotate_lock = threading.Lock()

    @classmethod
    def get(cls) -> KeyRotator:
        """Lazy singleton — reads keys from settings on first call."""
        if cls._instance is not None:
            return cls._instance
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            settings = get_settings()
            # Prefer comma-separated GROQ_API_KEYS; fallback to single key
            raw = (settings.groq_api_keys or "").strip()
            if raw:
                keys = [k.strip() for k in raw.split(",") if k.strip()]
            else:
                keys = [settings.groq_api_key] if settings.groq_api_key else []
            if not keys:
                raise ValueError(
                    "No Groq API keys configured. "
                    "Set GROQ_API_KEYS (comma-separated) or GROQ_API_KEY in .env"
                )
            cls._instance = cls(keys)
            logger.info(
                f"KeyRotator initialised with {len(keys)} key(s), "
                f"min gap {cls._instance._min_gap}s/key"
            )
            return cls._instance

    @property
    def num_keys(self) -> int:
        return len(self._keys)

    def next_key(self) -> str:
        """Return the next API key, blocking if needed to respect TPM."""
        with self._rotate_lock:
            idx = self._idx % len(self._keys)
            self._idx += 1

        # Throttle: wait if this key was used too recently
        now = time.monotonic()
        last = self._last_call.get(idx, 0.0)
        wait = self._min_gap - (now - last)
        if wait > 0:
            logger.debug(
                f"[KeyRotator] Key #{idx + 1} throttled — sleeping {wait:.1f}s"
            )
            time.sleep(wait)

        self._last_call[idx] = time.monotonic()
        return self._keys[idx]


# ═══════════════════════════════════════════════════════════
#  LLM Call Tracker — per-agent call count, token count & timing
# ═══════════════════════════════════════════════════════════

class LLMCallTracker:
    """Thread-safe tracker for LLM call statistics per agent.

    Usage:
        tracker = LLMCallTracker.get()
        tracker.set_context("C1_ARCHITECTURE_PLANNING")
        # … agent runs, llm calls auto-record …
        stats = tracker.get_all_stats()
    """

    _instance: LLMCallTracker | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._current_agent = threading.local()
        self._stats_lock = threading.Lock()
        # agent_name -> {"calls": int, "total_tokens": int,
        #                "start_time": float, "elapsed_seconds": float}
        self._stats: dict[str, dict] = {}

    @classmethod
    def get(cls) -> LLMCallTracker:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_context(self, agent_name: str) -> None:
        """Set the current agent context (called before agent.process)."""
        self._current_agent.name = agent_name
        with self._stats_lock:
            if agent_name not in self._stats:
                self._stats[agent_name] = {
                    "calls": 0,
                    "total_tokens": 0,
                    "start_time": time.monotonic(),
                    "elapsed_seconds": 0.0,
                }
            else:
                # Agent running again (e.g. retry) — reset timer
                self._stats[agent_name]["start_time"] = time.monotonic()

    def finish_context(self, agent_name: str) -> None:
        """Mark agent as finished — records elapsed time."""
        with self._stats_lock:
            entry = self._stats.get(agent_name)
            if entry and entry.get("start_time"):
                entry["elapsed_seconds"] = (
                    time.monotonic() - entry["start_time"]
                )

    def record_call(self, tokens_used: int = 0) -> None:
        """Record one LLM call under the current agent context."""
        agent = getattr(self._current_agent, "name", "UNKNOWN")
        with self._stats_lock:
            entry = self._stats.setdefault(agent, {
                "calls": 0, "total_tokens": 0,
                "start_time": time.monotonic(), "elapsed_seconds": 0.0,
            })
            entry["calls"] += 1
            entry["total_tokens"] += tokens_used

    def get_all_stats(self) -> dict[str, dict]:
        """Return a snapshot of all agent stats (safe to serialise)."""
        with self._stats_lock:
            return {
                agent: {
                    "llm_calls": s["calls"],
                    "total_tokens": s["total_tokens"],
                    "time_taken_seconds": round(s["elapsed_seconds"], 2),
                }
                for agent, s in self._stats.items()
            }

    def reset(self) -> None:
        """Clear all stats (e.g. between pipeline runs)."""
        with self._stats_lock:
            self._stats.clear()


# ═══════════════════════════════════════════════════════════
#  Helper — extract token count from response metadata
# ═══════════════════════════════════════════════════════════

def _extract_token_count(response) -> int:
    """Best-effort extraction of total token usage from LLM response."""
    meta = getattr(response, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage", {})
    if isinstance(usage, dict):
        return usage.get("total_tokens", 0)
    return 0


# ═══════════════════════════════════════════════════════════
#  LLM Client — replaces singleton with per-call key rotation
# ═══════════════════════════════════════════════════════════

def get_llm():
    """
    Return a Groq LLM client using the next rotated API key.
    Creates a fresh instance each time to use the rotated key.
    """
    settings = get_settings()
    rotator = KeyRotator.get()
    api_key = rotator.next_key()

    from langchain_groq import ChatGroq

    llm = ChatGroq(
        api_key=api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    return llm


def llm_json_call(prompt: str, output_model: Type[T]) -> T:
    """
    Call the LLM and parse the response into a Pydantic model.
    Uses LangChain's with_structured_output() for reliable JSON parsing.
    """
    tracker = LLMCallTracker.get()

    logger.debug(
        f"[LLM-JSON] Prompt length: {len(prompt)} chars | "
        f"Target model: {output_model.__name__}"
    )
    logger.debug(f"[LLM-JSON] Prompt preview:\n{prompt[:500]}{'…' if len(prompt) > 500 else ''}")

    llm = get_llm()
    structured_llm = llm.with_structured_output(output_model)

    t0 = time.perf_counter()
    result = structured_llm.invoke(prompt)
    elapsed = time.perf_counter() - t0

    # Track call
    tracker.record_call(tokens_used=0)  # structured output doesn't expose meta easily

    logger.info(f"[LLM-JSON] Response received in {elapsed:.2f}s | Model: {output_model.__name__}")
    logger.debug(f"[LLM-JSON] Parsed result: {result}")
    return result


def llm_text_call(prompt: str, max_retries: int = 2, deterministic: bool = False) -> str:
    """
    Call the LLM and return the raw text response.
    Retries up to *max_retries* times on empty responses.

    When *deterministic* is True, a dedicated LLM instance with
    temperature=0 and top_p=1 is used instead of the shared singleton.
    This ensures reproducible output for analytical/classification tasks.
    """
    tracker = LLMCallTracker.get()

    tag = "[LLM-TEXT-DET]" if deterministic else "[LLM-TEXT]"

    logger.debug(
        f"{tag} Prompt length: {len(prompt)} chars"
    )
    logger.debug(f"{tag} Prompt preview:\n{prompt[:500]}{'…' if len(prompt) > 500 else ''}")

    settings = get_settings()
    rotator = KeyRotator.get()

    if deterministic:
        from langchain_groq import ChatGroq

        api_key = rotator.next_key()
        llm = ChatGroq(
            api_key=api_key,
            model=settings.llm_model,
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
            model_kwargs={"top_p": 1.0, "seed": 42},
        )
    else:
        llm = get_llm()

    attempts = max_retries + 1

    for attempt in range(1, attempts + 1):
        t0 = time.perf_counter()
        try:
            response = llm.invoke(prompt)
        except Exception as exc:
            exc_str = str(exc)
            if "413" in exc_str or "429" in exc_str or "503" in exc_str or "rate_limit" in exc_str.lower():
                if attempt < attempts:
                    wait = min(30, 10 * attempt)
                    logger.warning(
                        f"{tag} Rate limit hit (attempt {attempt}/{attempts}). "
                        f"Waiting {wait}s for TPM window to reset..."
                    )
                    time.sleep(wait)
                    continue
                else:
                    logger.error(f"{tag} Rate limit exceeded on final attempt: {exc}")
            raise
        elapsed = time.perf_counter() - t0
        content = response.content or ""

        # Log response metadata (finish_reason, token usage)
        meta = getattr(response, "response_metadata", {}) or {}
        finish_reason = meta.get("finish_reason", "unknown")
        usage = meta.get("token_usage") or meta.get("usage", {})
        total_tokens = _extract_token_count(response)
        logger.info(
            f"{tag} Response received in {elapsed:.2f}s | "
            f"Response length: {len(content)} chars | "
            f"finish_reason={finish_reason} | "
            f"tokens={usage}"
        )
        logger.debug(f"{tag} Full response:\n{content}")

        # Track call
        tracker.record_call(tokens_used=total_tokens)

        if content.strip():
            return _strip_think_tags(content)

        # Empty response — warn and retry if allowed
        logger.warning(
            f"{tag} Empty response on attempt {attempt}/{attempts} "
            f"(finish_reason={finish_reason}). "
            f"{'Retrying…' if attempt < attempts else 'No retries left.'}"
        )

    return _strip_think_tags(content)  # return whatever we got (empty string)


def llm_deterministic_call(prompt: str, max_retries: int = 1) -> str:
    """
    Call the LLM with deterministic settings (temperature=0, top_p=1).

    Used exclusively by B1 Requirements Extraction to ensure reproducible
    output.  Creates a dedicated LLM instance separate from the shared
    singleton so other agents keep their own temperature settings.
    """
    tracker = LLMCallTracker.get()
    settings = get_settings()
    rotator = KeyRotator.get()

    from langchain_groq import ChatGroq

    api_key = rotator.next_key()
    llm = ChatGroq(
        api_key=api_key,
        model=settings.llm_model,
        temperature=settings.extraction_llm_temperature,  # 0.0
        max_tokens=settings.llm_max_tokens,
        model_kwargs={"top_p": settings.extraction_llm_top_p, "seed": 42},  # 1.0
    )

    logger.debug(
        f"[LLM-DET] Prompt length: {len(prompt)} chars | "
        f"temp={settings.extraction_llm_temperature} top_p={settings.extraction_llm_top_p}"
    )

    attempts = max_retries + 1
    content = ""

    for attempt in range(1, attempts + 1):
        t0 = time.perf_counter()
        try:
            response = llm.invoke(prompt)
        except Exception as exc:
            exc_str = str(exc)
            if "413" in exc_str or "429" in exc_str or "503" in exc_str or "rate_limit" in exc_str.lower():
                if attempt < attempts:
                    wait = min(30, 10 * attempt)
                    logger.warning(
                        f"[LLM-DET] Rate limit hit (attempt {attempt}/{attempts}). "
                        f"Waiting {wait}s..."
                    )
                    time.sleep(wait)
                    continue
                else:
                    logger.error(f"[LLM-DET] Rate limit exceeded on final attempt: {exc}")
            raise
        elapsed = time.perf_counter() - t0
        content = response.content or ""

        meta = getattr(response, "response_metadata", {}) or {}
        finish_reason = meta.get("finish_reason", "unknown")
        usage = meta.get("token_usage") or meta.get("usage", {})
        total_tokens = _extract_token_count(response)
        logger.info(
            f"[LLM-DET] Response in {elapsed:.2f}s | "
            f"len={len(content)} chars | "
            f"finish_reason={finish_reason} | tokens={usage}"
        )

        # Track call
        tracker.record_call(tokens_used=total_tokens)

        if content.strip():
            return _strip_think_tags(content)

        logger.warning(
            f"[LLM-DET] Empty response attempt {attempt}/{attempts} "
            f"(finish_reason={finish_reason})"
        )

    return _strip_think_tags(content)
