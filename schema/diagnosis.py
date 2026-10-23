"""Typed contract for everything the agent is allowed to output.

The LLM never emits shell commands: its only way to act is an ActionProposal
(a runbook id plus typed parameters), which the policy engine validates.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

EvidenceKind = Literal["metric", "trace", "log", "deploy", "flag", "topology"]


class Evidence(BaseModel):
    kind: EvidenceKind
    ref: str = Field(description="trace id, log line id, query, or flag name")
    summary: str
    window: str | None = Field(default=None, description="time window, e.g. 'last 5m'")


class Hypothesis(BaseModel):
    root_cause: str
    service: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)


class ActionProposal(BaseModel):
    runbook_id: str
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    rationale: str


class Diagnosis(BaseModel):
    incident_id: str
    summary: str
    top: Hypothesis | None = None
    alternatives: list[Hypothesis] = Field(default_factory=list)
    abstain: bool = False
    abstain_reason: str | None = None
    proposed_action: ActionProposal | None = None
    # Filled by the deterministic grounding check, never by the model.
    grounding: float | None = Field(default=None, description="fraction of cited evidence refs verified in observed data")
    ungrounded_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_grounding(self) -> "Diagnosis":
        if self.abstain:
            if not self.abstain_reason:
                raise ValueError("abstain requires abstain_reason")
            if self.proposed_action is not None:
                raise ValueError("an abstaining diagnosis must not propose an action")
            return self
        if self.top is None:
            raise ValueError("non-abstaining diagnosis requires a top hypothesis")
        if not self.top.evidence:
            raise ValueError("top hypothesis must cite at least one piece of evidence")
        return self
