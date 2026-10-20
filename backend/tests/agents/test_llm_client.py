"""P3.1 / P3.2: LLM client (mocked — no tokens spent) and prompt loader."""

from types import SimpleNamespace

import httpx
import openai
import pytest

from compliance.llm import client as client_mod
from compliance.llm import prompts
from compliance.llm.client import LLMClient, LLMError
from compliance.llm.models import RoleConfig, load_roles
from compliance.store.db import Database
from compliance.store.repo import Store

SCHEMA = {
    "name": "answer",
    "schema": {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
        "additionalProperties": False,
    },
}


def response(content="", tool_args=None, prompt=10, completion=5):
    calls = None
    if tool_args is not None:
        calls = [
            SimpleNamespace(id="c1", function=SimpleNamespace(name="answer", arguments=tool_args))
        ]
    msg = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


class FakeOpenAI:
    """Replays queued responses / exceptions and records every request."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def store(tmp_path):
    return Store(Database(tmp_path / "t.sqlite"))


def make(replies, store=None):
    fake = FakeOpenAI(replies)
    return LLMClient(store, client_factory=lambda base: fake, sleep=lambda s: None), fake


def test_roles_load_from_models_yaml():
    roles = load_roles()
    assert {"agent", "fast", "reviewer"} <= set(roles)
    assert roles["agent"].model.startswith("nvidia/")
    assert roles["fast"].reasoning_default is False and roles["agent"].reasoning_default is True


def test_plain_chat_uses_role_model_and_reasoning_toggle(store):
    llm, fake = make([response("<think>hmm</think> Hello")], store)
    r = llm.chat("fast", [{"role": "user", "content": "hi"}], purpose="test")
    assert r.content == "Hello"  # thinking stripped
    req = fake.requests[0]
    assert req["model"] == load_roles()["fast"].model
    assert req["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    llm2, fake2 = make([response("x")])
    llm2.chat("fast", [{"role": "user", "content": "hi"}], reasoning=True)
    assert fake2.requests[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    [row] = store.usage_summary()["models"]
    assert row["calls"] == 1 and row["prompt_tokens"] == 10


def test_schema_output_is_parsed_and_validated():
    llm, fake = make([response('```json\n{"n": 5}\n```')])
    r = llm.chat("agent", [{"role": "user", "content": "2+3"}], schema=SCHEMA)
    assert r.data == {"n": 5}
    assert fake.requests[0]["response_format"]["type"] == "json_schema"


def test_invalid_json_gets_one_repair_then_fails():
    llm, fake = make([response('{"n": "five"}'), response('{"n": 5}')])
    assert llm.chat("agent", [{"role": "user", "content": "q"}], schema=SCHEMA).data == {"n": 5}
    repair = fake.requests[1]["messages"][-1]["content"]
    assert "doesn't match the required schema" in repair

    llm, _ = make([response("nope"), response("still nope")])
    with pytest.raises(LLMError, match="invalid JSON"):
        llm.chat("agent", [{"role": "user", "content": "q"}], schema=SCHEMA)


def test_tool_call_fallback_when_model_lacks_json_schema(monkeypatch):
    cfg = RoleConfig(
        "agent",
        "m",
        None,
        tools=True,
        json_schema=False,
        reasoning_method=None,
        reasoning_default=False,
    )
    monkeypatch.setattr(client_mod, "role", lambda name: cfg)
    llm, fake = make([response("", tool_args='{"n": 7}')])
    assert llm.chat("agent", [{"role": "user", "content": "q"}], schema=SCHEMA).data == {"n": 7}
    req = fake.requests[0]
    assert req["tool_choice"]["function"]["name"] == "answer"
    assert "response_format" not in req and "extra_body" not in req


def test_transient_errors_retry_then_give_up(store):
    req = httpx.Request("POST", "http://x")
    timeout = openai.APITimeoutError(request=req)
    llm, fake = make([timeout, response("ok")], store)
    assert llm.chat("fast", [{"role": "user", "content": "q"}]).content == "ok"
    assert len(fake.requests) == 2

    llm, _ = make([timeout, timeout, timeout], store)
    with pytest.raises(LLMError, match="after 3 attempts"):
        llm.chat("fast", [{"role": "user", "content": "q"}])
    calls = store.usage_summary()["models"][0]
    assert calls["calls"] == 5 and calls["ok_calls"] == 1


def test_non_transient_errors_fail_fast():
    req = httpx.Request("POST", "http://x")
    bad = openai.BadRequestError("bad", response=httpx.Response(400, request=req), body=None)
    llm, fake = make([bad])
    with pytest.raises(LLMError, match="request failed"):
        llm.chat("fast", [{"role": "user", "content": "q"}])
    assert len(fake.requests) == 1


def test_prompt_loader(tmp_path, monkeypatch):
    (tmp_path / "demo.md").write_text(
        "---\nrole: demo\nmodel_role: fast\nversion: 2\n---\n"
        'Rule {{rule_id}} as JSON like {"a": 1}.\n',
        encoding="utf-8",
    )
    (tmp_path / "bad.md").write_text("no front matter", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS", tmp_path)
    prompts.load.cache_clear()
    meta, text = prompts.render("demo", rule_id="x.y")
    assert meta["model_role"] == "fast"
    assert text == 'Rule x.y as JSON like {"a": 1}.'
    assert prompts.version_tag("demo") == "demo-v2"
    with pytest.raises(prompts.PromptError, match="needs values"):
        prompts.render("demo")
    with pytest.raises(prompts.PromptError, match="front-matter"):
        prompts.load("bad")
    with pytest.raises(prompts.PromptError, match="not found"):
        prompts.load("missing")
    prompts.load.cache_clear()
