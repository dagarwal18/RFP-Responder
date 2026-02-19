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
    llm = get_llm()
    structured_llm = llm.with_structured_output(output_model)
    result = structured_llm.invoke(prompt)
    return result


def llm_text_call(prompt: str) -> str:
    """
    Call the LLM and return the raw text response.
    """
    llm = get_llm()
    response = llm.invoke(prompt)
    return response.content
