"""Shared LLM utilities: model selection, invocation, and JSON extraction.

Model IDs are configurable via environment variables so a model upgrade
never requires touching agent code:
    JOB_INTEL_FAST_MODEL    — extraction/scoring (default: Claude Haiku)
    JOB_INTEL_WRITER_MODEL  — prose generation (default: Claude Sonnet)
"""
from __future__ import annotations

import json
import os
import re
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

_DEFAULT_FAST_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_WRITER_MODEL = "claude-sonnet-4-5"

_FENCE_RE = re.compile(r"```(?:json)?")
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARR_RE = re.compile(r"\[.*\]", re.DOTALL)


def get_llm(role: Literal["fast", "writer"] = "fast", temperature: float = 0.0) -> ChatAnthropic:
    """Return a ChatAnthropic instance for the given role.

    Env vars are read at call time (not import time) so values from a
    late ``load_dotenv()`` are honoured.
    """
    if role == "writer":
        model = os.getenv("JOB_INTEL_WRITER_MODEL", _DEFAULT_WRITER_MODEL)
    else:
        model = os.getenv("JOB_INTEL_FAST_MODEL", _DEFAULT_FAST_MODEL)
    return ChatAnthropic(model=model, temperature=temperature)


def invoke_text(llm: ChatAnthropic, prompt: str) -> str:
    """Invoke the LLM with a single human message and return its text content."""
    msg = llm.invoke([HumanMessage(content=prompt)])
    return msg.content if isinstance(msg.content, str) else ""


def extract_json_object(text: str) -> dict | None:
    """Parse the first JSON object out of arbitrary LLM text. None on failure."""
    text = _FENCE_RE.sub("", text).strip()
    match = _JSON_OBJ_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_json_array(text: str) -> list | None:
    """Parse the first JSON array out of arbitrary LLM text. None on failure."""
    text = _FENCE_RE.sub("", text).strip()
    match = _JSON_ARR_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None
