"""The one place the app talks to a language model.

Every AI feature (grading, hint chat, performance narrative) goes through
complete(), so the provider and models are configured in one spot and tests
can replace complete() without touching the network.
"""

import os

from openai import OpenAI

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")


class LLMError(Exception):
    pass


_client = None


def _get_client():
    global _client
    if _client is None:
        # The account's per-minute token limit is low (30k TPM on gpt-4o), and one
        # grading uses ~12k tokens, so two students submitting together hit 429s.
        # The SDK backs off using the server's retry-after hint; the default of 2
        # retries isn't enough to ride out a busy minute.
        _client = OpenAI(max_retries=6, timeout=180)
    return _client


def _is_reasoning_model(model):
    # gpt-5.x / o-series reject a custom temperature; older chat models accept it.
    return not model.startswith(("gpt-4", "gpt-3"))


def complete(messages, *, model=None, json_schema=None, max_tokens=None, temperature=None):
    """Return the model's text reply. Raises LLMError on any provider failure."""
    model = model or DEFAULT_MODEL
    kwargs = {"model": model, "messages": messages}
    if json_schema is not None:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": json_schema}
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    if temperature is not None and not _is_reasoning_model(model):
        kwargs["temperature"] = temperature
    try:
        response = _get_client().chat.completions.create(**kwargs)
    except Exception as exc:
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    content = response.choices[0].message.content
    if not content:
        raise LLMError(f"empty response (finish_reason={response.choices[0].finish_reason})")
    return content
