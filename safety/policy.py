"""Deterministic policy engine. The LLM proposes; this module disposes.

Safe by construction: an action is only a (runbook_id, params) pair. Params are
validated against the runbook's declared typed schema and allowed values, so
free-form text from the model (or injected via logs) can never become a command.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from schema import ActionProposal

from .killswitch import KillSwitch

Risk = Literal["low", "medium", "high"]


class ParamSpec(BaseModel):
    type: Literal["str", "int", "float", "bool"]
    allowed: list[str | int | float | bool] = Field(description="closed set of permitted values")


class Runbook(BaseModel):
    id: str
    description: str
    risk: Risk
    requires_approval: bool = True
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    # Fixed argv template; {name} placeholders are filled only from validated params.
    argv: list[str]
    dry_run_argv: list[str] | None = None
    rollback_argv: list[str] | None = None
    verify_query: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    runbook: Runbook | None = None
    needs_approval: bool = True


_PY = {"str": str, "int": int, "float": float, "bool": bool}


def load_runbooks(directory: Path) -> dict[str, Runbook]:
    books: dict[str, Runbook] = {}
    for path in sorted(directory.glob("*.yaml")):
        rb = Runbook.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        books[rb.id] = rb
    return books


class PolicyEngine:
    def __init__(self, runbooks: dict[str, Runbook], killswitch: KillSwitch) -> None:
        self._runbooks = runbooks
        self._kill = killswitch

    def evaluate(self, proposal: ActionProposal) -> PolicyDecision:
        if self._kill.engaged():
            return PolicyDecision(False, "kill switch engaged")
        rb = self._runbooks.get(proposal.runbook_id)
        if rb is None:
            return PolicyDecision(False, f"runbook '{proposal.runbook_id}' is not on the allowlist")
        if set(proposal.params) != set(rb.params):
            return PolicyDecision(False, "params do not match runbook schema exactly", rb)
        for name, spec in rb.params.items():
            value = proposal.params[name]
            py = _PY[spec.type]
            # bool is a subclass of int; require exact type to block coercion tricks.
            if type(value) is not py:
                return PolicyDecision(False, f"param '{name}' must be {spec.type}", rb)
            if value not in spec.allowed:
                return PolicyDecision(False, f"param '{name}'={value!r} not in allowed set", rb)
        needs = rb.requires_approval or rb.risk != "low"
        return PolicyDecision(True, "ok", rb, needs_approval=needs)

    @staticmethod
    def render_argv(rb: Runbook, params: dict, dry_run: bool = False) -> list[str]:
        template = rb.dry_run_argv if dry_run and rb.dry_run_argv else rb.argv
        return [part.format(**{k: str(v) for k, v in params.items()}) for part in template]
