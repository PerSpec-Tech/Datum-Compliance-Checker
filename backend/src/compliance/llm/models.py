"""Model roles: the only code that reads backend/config/models.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from compliance.config import get_settings

ROLES = ("agent", "fast", "reviewer")


@dataclass(frozen=True)
class RoleConfig:
    role: str
    model: str
    base_url: str | None
    tools: bool
    json_schema: bool
    reasoning_method: str | None  # e.g. "chat_template_kwargs"; None = can't toggle
    reasoning_default: bool


@lru_cache
def load_roles(path: Path | None = None) -> dict[str, RoleConfig]:
    doc = yaml.safe_load((path or get_settings().models_file).read_text(encoding="utf-8"))
    out: dict[str, RoleConfig] = {}
    for role, cfg in (doc.get("roles") or {}).items():
        if not cfg.get("model"):
            continue
        reasoning = cfg.get("reasoning") or {}
        default = reasoning.get("default")
        out[role] = RoleConfig(
            role=role,
            model=cfg["model"],
            base_url=cfg.get("base_url"),
            tools=bool(cfg.get("tools")),
            json_schema=bool(cfg.get("json_schema")),
            reasoning_method=reasoning.get("method"),
            reasoning_default=default in (True, "on", "true"),
        )
    return out


def role(name: str) -> RoleConfig:
    roles = load_roles()
    if name not in roles:
        raise KeyError(f"model role '{name}' is not configured in backend/config/models.yaml")
    return roles[name]
