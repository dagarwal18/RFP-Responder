"""
LLM Service — centralized Groq Cloud LLM client.

All agents use this module to make LLM calls. Provides:
  - get_llm()         → returns configured Groq ChatModel
  - llm_json_call()   → structured output (parsed into Pydantic model)
  - llm_text_call()   → raw text response
"""

from __future__ import annotations

import logging
from typing import Type, TypeVar

from pydantic import BaseModel

from rfp_automation.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_llm_instance = None


def get_llm():
    """
    Return a configured Groq LLM client (singleton).
    Uses langchain-groq's ChatGroq.
    """
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    settings = get_settings()

    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not set in environment / .env file")

    from langchain_groq import ChatGroq

    _llm_instance = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    logger.info(f"Initialized Groq LLM: {settings.llm_model}")
    return _llm_instance


def llm_json_call(prompt: str, output_model: Type[T]) -> T:
    """
    Call the LLM and parse the response into a Pydantic model.
    Uses LangChain's with_structured_output() for reliable JSON parsing.
    """
    import time

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

    logger.info(f"[LLM-JSON] Response received in {elapsed:.2f}s | Model: {output_model.__name__}")
    logger.debug(f"[LLM-JSON] Parsed result: {result}")
    return result


def llm_text_call(prompt: str) -> str:
    """
    Call the LLM and return the raw text response.
    """
    import time

    logger.debug(
        f"[LLM-TEXT] Prompt length: {len(prompt)} chars"
    )
    logger.debug(f"[LLM-TEXT] Prompt preview:\n{prompt[:500]}{'…' if len(prompt) > 500 else ''}")

    llm = get_llm()
    t0 = time.perf_counter()
    response = llm.invoke(prompt)
    elapsed = time.perf_counter() - t0
    content = response.content

    logger.info(
        f"[LLM-TEXT] Response received in {elapsed:.2f}s | "
        f"Response length: {len(content)} chars"
    )
    logger.debug(f"[LLM-TEXT] Full response:\n{content}")
    return content
