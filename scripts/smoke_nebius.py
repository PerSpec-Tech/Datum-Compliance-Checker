"""P0.5: verify Nemotron models on Nebius Token Factory and record capabilities per role.

Usage: just smoke-llm            (report only)
       just smoke-llm --write    (also rewrite backend/config/models.yaml)
"""

import json
import sys
import time
from datetime import date

import yaml
from openai import OpenAI

from compliance.config import get_settings

ROLE_MATCH = {  # role -> (must contain all, must contain none)
    "agent": (["nemotron", "super"], ["omni"]),
    "fast": (["nemotron", "nano"], ["omni", "vl"]),
    "reviewer": (["nemotron", "ultra"], ["omni"]),
    "vision": (["nemotron", "omni"], []),
}

TOOL = {
    "type": "function",
    "function": {
        "name": "get_room_area",
        "description": "Return the floor area of a room in square metres.",
        "parameters": {
            "type": "object",
            "properties": {"room": {"type": "string"}},
            "required": ["room"],
        },
    },
}

SCHEMA = {
    "name": "sum_result",
    "schema": {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
    "strict": True,
}


def pick(ids: list[str], role: str) -> str | None:
    need, avoid = ROLE_MATCH[role]
    hits = [
        m
        for m in ids
        if all(k in m.lower() for k in need) and not any(k in m.lower() for k in avoid)
    ]
    # Prefer the plain variant over "-fast"/"-base" style suffixes.
    hits.sort(key=lambda m: (("fast" in m.lower()) or ("base" in m.lower()), len(m)))
    return hits[0] if hits else None


def has_reasoning(msg) -> bool:
    extra = getattr(msg, "model_extra", None) or {}
    rc = extra.get("reasoning_content") or extra.get("reasoning")
    return bool(rc) or "<think>" in (msg.content or "")


def run(client: OpenAI, model: str, **kw):
    t = time.perf_counter()
    r = client.chat.completions.create(model=model, max_tokens=kw.pop("max_tokens", 400), **kw)
    return r, round(time.perf_counter() - t, 2)


def check_role(client: OpenAI, model: str) -> dict:
    out: dict = {"model": model, "verified": False}
    msgs = [{"role": "user", "content": "Reply with the single word OK."}]

    try:
        r, s = run(client, model, messages=msgs)
        out["verified"] = True
        print(f"    chat        ok ({s}s): {(r.choices[0].message.content or '').strip()[:60]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"    chat        FAIL: {e}")
        return out

    try:
        r, s = run(
            client,
            model,
            tools=[TOOL],
            tool_choice="auto",
            messages=[
                {
                    "role": "user",
                    "content": "What is the area of the room 'Kitchen 1'? Use the tool.",
                }
            ],
        )
        calls = r.choices[0].message.tool_calls or []
        out["tools"] = bool(calls) and calls[0].function.name == "get_room_area"
        print(f"    tools       {out['tools']} ({s}s)")
    except Exception as e:  # noqa: BLE001
        out["tools"] = False
        print(f"    tools       FAIL: {e}")

    try:
        r, s = run(
            client,
            model,
            response_format={"type": "json_schema", "json_schema": SCHEMA},
            messages=[
                {"role": "user", "content": 'What is 2 + 3? Answer as JSON {"answer": <int>}.'}
            ],
        )
        data = json.loads(r.choices[0].message.content or "")
        out["json_schema"] = data.get("answer") == 5
        print(f"    json_schema {out['json_schema']} ({s}s)")
    except Exception as e:  # noqa: BLE001
        out["json_schema"] = False
        print(f"    json_schema FAIL: {e}")

    # Reasoning toggle: try chat_template_kwargs first, then the /think and /no_think system flags.
    q = [{"role": "user", "content": "Is 17 a prime number? Answer yes or no."}]
    method = None
    for name, on_kw, off_kw in [
        (
            "chat_template_kwargs",
            {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}, "messages": q},
            {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}, "messages": q},
        ),
        (
            "system_prompt",
            {"messages": [{"role": "system", "content": "/think"}, *q]},
            {"messages": [{"role": "system", "content": "/no_think"}, *q]},
        ),
    ]:
        try:
            r_on, _ = run(client, model, max_tokens=1200, **on_kw)
            r_off, _ = run(client, model, max_tokens=1200, **off_kw)
            on, off = (
                has_reasoning(r_on.choices[0].message),
                has_reasoning(r_off.choices[0].message),
            )
            print(f"    reasoning   {name}: on={on} off={off}")
            if on and not off:
                method = name
                break
        except Exception as e:  # noqa: BLE001
            print(f"    reasoning   {name} FAIL: {e}")
    out["reasoning_method"] = method
    return out


def main() -> int:
    write = "--write" in sys.argv
    s = get_settings()
    if not s.nebius_api_key:
        print("NEBIUS_API_KEY is empty. Fill in .env (P0.3) first.")
        return 1
    client = OpenAI(base_url=s.nebius_base_url, api_key=s.nebius_api_key, timeout=120)

    ids = sorted(m.id for m in client.models.list().data)
    nemo = [m for m in ids if "nemotron" in m.lower()]
    print(f"{len(ids)} models available; {len(nemo)} Nemotron:")
    for m in nemo:
        print(f"  - {m}")
    emb = [m for m in ids if "embed" in m.lower()]
    print(f"Embedding models: {emb or 'none'}")

    cfg = yaml.safe_load(s.models_file.read_text(encoding="utf-8"))
    for role in ROLE_MATCH:
        model = pick(nemo, role)
        print(f"\n[{role}] -> {model}")
        if not model:
            continue
        res = check_role(client, model)
        entry = cfg["roles"][role]
        entry.update(
            model=res["model"],
            verified=res["verified"],
            tools=res.get("tools"),
            json_schema=res.get("json_schema"),
        )
        entry["reasoning"]["method"] = res.get("reasoning_method")

    if write:
        cfg["checked"] = date.today().isoformat()
        header = s.models_file.read_text(encoding="utf-8").split("\nchecked:")[0]
        body = yaml.safe_dump({"checked": cfg["checked"], "roles": cfg["roles"]}, sort_keys=False)
        s.models_file.write_text(header + "\n" + body, encoding="utf-8")
        print(f"\nWrote {s.models_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
