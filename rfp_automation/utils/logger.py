"""Centralized logging configuration.
Call setup_logging() once at application startup.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "DEBUG") -> None:
    """Configure structured logging for the pipeline with full debug output."""
    root = logging.getLogger()
    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    root.setLevel(getattr(logging, level))

    # Use a stream wrapper that can handle Unicode on Windows consoles
    import io
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    handler = logging.StreamHandler(stream)
    handler.setLevel(getattr(logging, level))

    formatter = logging.Formatter(
        fmt=(
            "\n%(asctime)s │ %(levelname)-8s │ %(name)s │ %(funcName)s:%(lineno)d\n"
            "  %(message)s"
        ),
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet noisy libraries but keep our code at DEBUG
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.INFO)
    logging.getLogger("langchain_core").setLevel(logging.INFO)
    logging.getLogger("langchain_groq").setLevel(logging.INFO)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("pinecone").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
