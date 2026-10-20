"""Nebius Token Factory client (P3.1). Every LLM call in the app goes through `LLMClient.chat`.

- The model comes from the role (agent / fast / reviewer), never from the caller (CLAUDE.md).
- Reasoning ("thinking") is switched per call or per role default, using the method P0.5 verified.
- `schema=` asks for structured JSON (json_schema response format, or a forced tool call when the
  model can't do json_schema), validates it, and gives the model one chance to repair it.
- Transient errors are retried 3 times with exponential backoff; each attempt is logged to
  llm_usage (the judges' proof of Nebius / NVIDIA use, P7.4).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema
import openai
from openai import OpenAI

from compliance.config import get_settings
from compliance.llm.models import RoleConfig, role
from compliance.store.repo import Store

TIMEOUT_S = 120
ATTEMPTS = 3
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_TRANSIENT = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class LLMError(Exception):
    """The model call failed, or returned output that doesn't match the requested schema."""


@dataclass
class ChatResult:
    content: str
    data: Any = None  # parsed + validated JSON when a schema was requested
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient:
    def __init__(
        self,
        store: Store | None = None,
        *,
        client_factory: Callable[[str], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        settings = get_settings()
        self._default_base = settings.nebius_base_url
        self._store = store
        self._factory = client_factory or (
            lambda base: OpenAI(
                base_url=base, api_key=settings.nebius_api_key, timeout=TIMEOUT_S, max_retries=0
            )
        )
        self._clients: dict[str, Any] = {}
        self._sleep = sleep

    def chat(
        self,
        role_name: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning: bool | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        purpose: str | None = None,
        job_id: str | None = None,
    ) -> ChatResult:
        cfg = role(role_name)
        kwargs: dict[str, Any] = {"model": cfg.model, "max_tokens": max_tokens}
        if temperature is not None:
            kwargs["temperature"] = temperature
        think = cfg.reasoning_default if reasoning is None else reasoning
        if cfg.reasoning_method == "chat_template_kwargs":
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": think}}
        if tools:
            kwargs["tools"] = tools

        if schema is None:
            return self._call(cfg, messages, kwargs, purpose, job_id)

        use_tool = not cfg.json_schema
        if use_tool:
            kwargs["tools"] = [_schema_tool(schema)]
            kwargs["tool_choice"] = {"type": "function", "function": {"name": schema["name"]}}
        else:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema["name"], "schema": schema["schema"], "strict": True},
            }

        convo = list(messages)
        last_error = ""
        for attempt in range(2):  # first answer + one repair
            result = self._call(cfg, convo, kwargs, purpose, job_id)
            raw = (
                result.tool_calls[0]["arguments"]
                if use_tool and result.tool_calls
                else result.content
            )
            try:
                data = json.loads(_strip_fences(raw))
                jsonschema.validate(data, schema["schema"])
                result.data = data
                return result
            except (json.JSONDecodeError, jsonschema.ValidationError) as e:
                last_error = e.message if isinstance(e, jsonschema.ValidationError) else str(e)
                if attempt == 0:
                    convo = [
                        *convo,
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": "That JSON doesn't match the required schema: "
                            f"{last_error[:500]}. Reply with corrected JSON only.",
                        },
                    ]
        raise LLMError(
            f"{role_name} returned invalid JSON for '{schema['name']}': {last_error[:300]}"
        )

    # ------------------------------------------------------------------ internals

    def _client(self, cfg: RoleConfig) -> Any:
        base = cfg.base_url or self._default_base
        if base not in self._clients:
            self._clients[base] = self._factory(base)
        return self._clients[base]

    def _call(self, cfg: RoleConfig, messages, kwargs, purpose, job_id) -> ChatResult:
        client = self._client(cfg)
        for attempt in range(1, ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                resp = client.chat.completions.create(messages=messages, **kwargs)
            except _TRANSIENT as e:
                self._log(cfg, False, started, None, purpose, job_id)
                if attempt == ATTEMPTS:
                    raise LLMError(f"{cfg.role} unavailable after {ATTEMPTS} attempts: {e}") from e
                self._sleep(2 ** (attempt - 1))  # 1 s, 2 s
                continue
            except openai.APIError as e:
                self._log(cfg, False, started, None, purpose, job_id)
                raise LLMError(f"{cfg.role} request failed: {e}") from e
            self._log(cfg, True, started, getattr(resp, "usage", None), purpose, job_id)
            msg = resp.choices[0].message
            return ChatResult(
                content=_THINK.sub("", msg.content or "").strip(),
                tool_calls=[
                    {"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                    for c in (msg.tool_calls or [])
                ],
                model=cfg.model,
                prompt_tokens=getattr(resp.usage, "prompt_tokens", None) if resp.usage else None,
                completion_tokens=getattr(resp.usage, "completion_tokens", None)
                if resp.usage
                else None,
            )
        raise LLMError("unreachable")  # pragma: no cover

    def _log(self, cfg: RoleConfig, ok: bool, started: float, usage, purpose, job_id) -> None:
        if self._store is None:
            return
        self._store.record_llm_usage(
            role=cfg.role,
            model=cfg.model,
            ok=ok,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            purpose=purpose,
            job_id=job_id,
        )


def _schema_tool(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema.get("description", "Return the result."),
            "parameters": schema["schema"],
        },
    }


def _strip_fences(text: str) -> str:
    text = _THINK.sub("", text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    return text
