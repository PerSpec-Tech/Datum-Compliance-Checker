"""Prompt loader (P3.2). Prompts live only in backend/prompts/<name>.md (CLAUDE.md):

    ---
    role: compiler            # what the prompt is for
    model_role: agent         # agent | fast | reviewer
    version: 1                # bump when the wording changes; recorded with outputs
    ---
    System prompt text … {{placeholder}} …

Placeholders use double braces, so prompts can contain JSON examples with single braces freely.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from compliance.config import BACKEND_ROOT

PROMPTS = BACKEND_ROOT / "prompts"
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptError(Exception):
    pass


@lru_cache
def load(name: str) -> tuple[dict[str, Any], str]:
    path = PROMPTS / f"{name}.md"
    if not path.exists():
        raise PromptError(f"prompt '{name}' not found at {path}")
    m = _FRONT.match(path.read_text(encoding="utf-8"))
    if not m:
        raise PromptError(f"prompt '{name}' needs YAML front-matter between --- lines")
    meta = yaml.safe_load(m.group(1)) or {}
    for key in ("role", "model_role", "version"):
        if key not in meta:
            raise PromptError(f"prompt '{name}' front-matter is missing '{key}'")
    return meta, m.group(2).strip()


def render(name: str, **values: Any) -> tuple[dict[str, Any], str]:
    """(meta, text) with every {{placeholder}} filled. Missing values are an error."""
    meta, template = load(name)
    needed = set(_PLACEHOLDER.findall(template))
    missing = needed - set(values)
    if missing:
        raise PromptError(f"prompt '{name}' needs values for {sorted(missing)}")
    return meta, _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)


def version_tag(name: str) -> str:
    meta, _ = load(name)
    return f"{name}-v{meta['version']}"
