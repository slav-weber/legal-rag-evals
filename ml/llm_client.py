"""Thin OpenAI-compatible client for the local LM Studio server.

Phase L: every inference call runs on the local LM Studio OpenAI-compatible
endpoint (default ``http://localhost:1234/v1``). No external API keys, no cost.
Configuration comes from the environment (see ``.env.example``):

    LLM_BASE_URL, LLM_MODEL              -> chat()
    EMBEDDINGS_BASE_URL, EMBEDDINGS_MODEL -> embed()
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "")
DEFAULT_EMBEDDINGS_BASE_URL = os.getenv("EMBEDDINGS_BASE_URL", DEFAULT_BASE_URL)
DEFAULT_EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "")

# LM Studio ignores the API key, but the OpenAI client requires a non-empty value.
_API_KEY = os.getenv("LLM_API_KEY", "lm-studio")

# --- DeepSeek (EXTERNAL, PAID) — data-governance guardrail --------------------
# Enabled 2026-07-04; data policy SIMPLIFIED 2026-07-05.
# DeepSeek is a PRC service with NO zero-data-retention that trains on inputs, so:
#   MAY receive ANY OPEN data — legislation, court decisions from ЄДРСР (the public
#   court-decision register; parties are anonymised by the register as ОСОБА_N,
#   judges' names are public), Supreme Court reviews, public FAQ, templates, dev
#   fixtures.
#   MUST NEVER receive USER data or anything derived from it — raw intake, collected
#   client facts, generated client memos, clarifications, email/payment data. In
#   prod, user queries go only to an EU+ZDR model.
# Model policy (decided 2026-07-04, verified against api.deepseek.com/models
# and the pricing docs): the legacy aliases deepseek-chat / deepseek-reasoner are
# DEPRECATED on 2026-07-24; the API serves deepseek-v4-flash and deepseek-v4-pro.
# Default = v4-flash (cheap bulk synthetics / cross-checks); pass
# model="deepseek-v4-pro" explicitly for quality-critical cross-checks only.
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
_DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# Fail-fast: the SDK default can hang for hundreds of seconds (observed live).
DEEPSEEK_TIMEOUT = 30.0

# Tripwire (retuned 2026-07-05): USER data has no natural token, so the convention
# is to WRAP it with USER_DATA_SENTINEL (via mark_user_data) wherever real user
# input enters a prompt; chat_deepseek then refuses to send it. Open data
# (laws / ЄДРСР texts / FAQ) carries no such marker and flows freely. A seatbelt —
# not a substitute for routing user data to the local / prod-ZDR model to begin with.
USER_DATA_SENTINEL = "⁦PRAVO8_USER_DATA⁩"


def mark_user_data(text: str) -> str:
    """Wrap user-derived text so chat_deepseek's tripwire refuses to send it to the
    external API. Apply wherever real user input (or anything derived from it)
    enters a prompt that could reach an external provider."""
    return f"{USER_DATA_SENTINEL}{text}{USER_DATA_SENTINEL}"


@dataclass(frozen=True)
class ChatResult:
    """A single chat completion plus token accounting reported by the server."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@lru_cache(maxsize=4)
def _client(base_url: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=_API_KEY)


def _result_from(resp, fallback_model: str) -> ChatResult:
    usage = resp.usage
    return ChatResult(
        text=resp.choices[0].message.content or "",
        model=resp.model or fallback_model,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )


def chat(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    base_url: str | None = None,
) -> ChatResult:
    """Run a chat completion against the local model. Returns text + token usage."""
    base_url = base_url or DEFAULT_BASE_URL
    model = model or DEFAULT_MODEL
    if not model:
        raise ValueError("No chat model configured (set LLM_MODEL or pass model=).")

    resp = _client(base_url).chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return _result_from(resp, model)


def embed(
    texts: str | Iterable[str],
    model: str | None = None,
    *,
    base_url: str | None = None,
) -> list[list[float]]:
    """Embed one string or many. Always returns a list of vectors."""
    if isinstance(texts, str):
        texts = [texts]
    texts = list(texts)

    base_url = base_url or DEFAULT_EMBEDDINGS_BASE_URL
    model = model or DEFAULT_EMBEDDINGS_MODEL
    if not model:
        raise ValueError("No embeddings model configured (set EMBEDDINGS_MODEL or pass model=).")

    resp = _client(base_url).embeddings.create(model=model, input=texts)
    return [item.embedding for item in resp.data]


def list_models(base_url: str | None = None) -> list[str]:
    """List model identifiers currently served by the local endpoint."""
    base_url = base_url or DEFAULT_BASE_URL
    return [m.id for m in _client(base_url).models.list().data]


def deepseek_available() -> bool:
    """True if a DeepSeek API key is configured."""
    return bool(_DEEPSEEK_API_KEY)


# Scalars that provably carry no text (bool is an int subclass, so it's covered by int).
_SAFE_SCALARS = (int, float, type(None))


def _walk_strings(obj) -> list[str]:
    """Every string ANYWHERE in a nested structure — dict KEYS included. TRULY FAIL-CLOSED
    (a review finding): raises on any leaf we cannot reduce to text (bytes/set/tuple-of-bytes/
    custom object), because an unscannable value could smuggle a marked fragment past the
    tripwire. The old version silently returned [] for such types, and never scanned dict
    keys (a sentinel in a key went straight to the API)."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, _SAFE_SCALARS):
        return []
    if isinstance(obj, dict):
        out: list[str] = []
        for k, v in obj.items():
            out.extend(_walk_strings(k))   # keys scanned too
            out.extend(_walk_strings(v))
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for v in obj:
            out.extend(_walk_strings(v))
        return out
    raise ValueError(
        f"DeepSeek: uninspectable value of type {type(obj).__name__} in message — "
        "refusing (cannot verify it is PII-free).")


def _message_texts(m: dict) -> list[str]:
    """Every scannable text fragment of a message. FAIL-CLOSED on ``content``: raises if it
    carries a part we cannot reduce to inspectable text (image/binary/unknown). A text part is
    scanned for ALL its strings (not just ``text`` — a sibling field could carry the marker),
    and every non-content field is walked recursively (keys + values, all nesting)."""
    frags: list[str] = []
    content = m.get("content", "")
    if isinstance(content, str):
        frags.append(content)
    elif content is None:
        pass
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                frags.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                frags.extend(_walk_strings(part))   # ALL strings of the text part
            else:
                raise ValueError(
                    "DeepSeek: message content part is not inspectable text "
                    "(image/binary/unknown) — refusing (cannot verify it is PII-free).")
    else:
        raise ValueError(
            "DeepSeek: message content is neither a string nor a list of text parts "
            "— refusing (cannot verify it is PII-free).")
    # every OTHER field (tool_calls, name, …) — recursive fail-closed walk (keys + values).
    frags.extend(_walk_strings({k: v for k, v in m.items() if k != "content"}))
    return frags


def _guard_deepseek(messages: list[dict]) -> None:
    """Key check + USER_DATA tripwire shared by every DeepSeek entry point."""
    if not _DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set (DeepSeek is opt-in).")
    for m in messages:
        if m.get("user_data") or any(
                USER_DATA_SENTINEL in frag for frag in _message_texts(m)):
            raise ValueError(
                "DeepSeek: payload carries a USER_DATA marker — user data (or "
                "anything derived from it) must NEVER go to an external API. Open "
                "data (laws / ЄДРСР texts / FAQ) is allowed; user data is not."
            )


def _deepseek_client(timeout: float = DEEPSEEK_TIMEOUT):
    """Shared DeepSeek client factory — ALWAYS time-bounded with one retry, so no
    entry point can inherit the SDK's hang-forever default (hardening pass)."""
    return OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=_DEEPSEEK_API_KEY,
                  timeout=timeout, max_retries=1)


def _strictify_schema(schema):
    """Recursively enforce strict-mode JSON schema: EVERY object level gets
    additionalProperties:false and a required-superset of its properties — not just
    the top level — so nested objects are as strict as the root (hardening pass).
    Mutates and returns a copy-safe structure (call on a deepcopy)."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            props = schema.get("properties", {}) or {}
            schema["additionalProperties"] = False
            schema["required"] = list(props.keys())
            for v in props.values():
                _strictify_schema(v)
        if isinstance(schema.get("items"), (dict, list)):
            _strictify_schema(schema["items"])
        for comb in ("anyOf", "oneOf", "allOf"):
            for sub in schema.get(comb, []) or []:
                _strictify_schema(sub)
    elif isinstance(schema, list):
        for item in schema:
            _strictify_schema(item)
    return schema


def chat_deepseek(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    thinking: bool = False,
) -> ChatResult:
    """Chat via the DeepSeek API (EXTERNAL, PAID).

    GUARDRAIL: OPEN data only (see the DeepSeek policy note near the top of this
    module) — laws, ЄДРСР texts, reviews, FAQ are fine. USER data (or anything
    derived from it) must NEVER be sent; wrap such content with mark_user_data()
    at its source and the tripwire below refuses it. Raises if DEEPSEEK_API_KEY
    is unset.

    Thinking mode is ON server-side by default on v4 models and silently spends
    the max_tokens budget on reasoning (empty content on small budgets), so it
    is disabled here unless explicitly requested via thinking=True.
    """
    _guard_deepseek(messages)
    model = model or DEEPSEEK_MODEL
    client = _deepseek_client()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
    )
    return _result_from(resp, model)


@dataclass(frozen=True)
class ToolResult:
    """Parsed strict tool-call arguments + token accounting (incl. cache hits). `tool_call_id` +
    `raw_arguments` let a caller reconstruct the assistant tool-call turn for a multi-turn retry
    (the OpenAI/DeepSeek protocol wants the assistant tool_call + a tool response before the next
    turn, not a bare follow-up user message)."""

    args: dict
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hit_tokens: int
    request_id: str = ""
    tool_call_id: str = ""
    raw_arguments: str = ""


def call_tool_deepseek(
    messages: list[dict],
    tool: dict,
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float = DEEPSEEK_TIMEOUT,
) -> ToolResult:
    """Strict function-calling on DeepSeek.

    Forces the model to return arguments matching ``tool`` (a JSON-schema dict
    with name/description/parameters), using strict tools + forced tool_choice.
    thinking MUST stay disabled: v4 models return HTTP 400 on a forced
    tool_choice while thinking is on (verified live). temp defaults to 0.0 for
    mechanical/citation work; timeout=30s + max_retries=1 to fail fast. Same
    USER_DATA guardrail as chat_deepseek.
    """
    _guard_deepseek(messages)
    model = model or DEEPSEEK_MODEL
    params = _strictify_schema(copy.deepcopy(tool["parameters"]))
    tools = [{
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": params,
            "strict": True,
        },
    }]
    client = _deepseek_client(timeout)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": tool["name"]}},
        extra_body={"thinking": {"type": "disabled"}},
    )
    choice = resp.choices[0]
    calls = choice.message.tool_calls or []
    if not calls:
        raise RuntimeError(
            f"DeepSeek returned no tool call (finish_reason={choice.finish_reason}); "
            "if 'length', raise max_tokens."
        )
    try:
        args = json.loads(calls[0].function.arguments or "{}")
    except json.JSONDecodeError as exc:
        # finish_reason=length truncates the tool-args JSON mid-string (observed live).
        raise RuntimeError(
            f"DeepSeek tool-args JSON truncated (finish_reason={choice.finish_reason}) "
            f"— raise max_tokens: {exc}"
        ) from exc
    usage = resp.usage
    return ToolResult(
        args=args,
        model=resp.model or model,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
        cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
        request_id=getattr(resp, "id", "") or "",
        tool_call_id=getattr(calls[0], "id", "") or "",
        raw_arguments=calls[0].function.arguments or "{}",
    )
