"""Naive baseline for the ablation: one LLM call over raw container logs, no detectors, no novelty
tagging, no container-state view, no drill-down tools, no grounding. This is what a typical first-day
"LLM + logs" on-call bot does. It must emit the same Diagnosis schema so scoring is identical.
"""
from __future__ import annotations

import json
import uuid

from pydantic import ValidationError

from agent.grounding import ground
from agent.llm import LLM
from safety import load_runbooks
from schema import Diagnosis
from tools import telemetry
from tools.config import ROOT

SYSTEM = """You are an on-call engineer. You are given recent raw logs from every container of a shop and an alert.
Find the root cause and propose a fix from the approved runbooks only.
Output ONE JSON object: {"incident_id": str, "summary": str, "top": {"root_cause": str, "service": str,
"confidence": float, "evidence": [{"kind": "log", "ref": str, "summary": str, "window": null}]},
"alternatives": [], "abstain": bool, "abstain_reason": str|null,
"proposed_action": {"runbook_id": str, "params": {}, "rationale": str} | null}
If unsure, set abstain=true and propose no action."""


def _raw_logs(tail: int = 15, width: int = 200) -> str:
    import subprocess

    from tools.config import DOCKER
    names = subprocess.run([DOCKER, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    parts = []
    for n in names:
        lines = [l[:width] for l in telemetry.container_logs(n, tail)]
        parts.append(f"=== {n} ===\n" + "\n".join(lines))
    return "\n".join(parts)


def diagnose(alert: str, llm: LLM) -> Diagnosis:
    books = load_runbooks(ROOT / "runbooks")
    catalog = [{"id": r.id, "description": r.description, "params": {k: v.allowed for k, v in r.params.items()}}
               for r in books.values()]
    logs = _raw_logs()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ALERT: {alert}\n\nRUNBOOKS:\n{json.dumps(catalog)}\n\nLOGS:\n{logs}"}]
    incident_id = f"base-{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        msg = llm.chat(messages, json_mode=True)
        raw = (msg.content or "").strip().removeprefix("```json").removesuffix("```").strip()
        try:
            d = Diagnosis.model_validate_json(raw)
            d.incident_id = incident_id
            return ground(d, logs)
        except (ValidationError, ValueError) as e:
            messages += [{"role": "assistant", "content": msg.content or ""},
                         {"role": "user", "content": f"Invalid: {str(e)[:300]}. Return corrected JSON only."}]
    return Diagnosis(incident_id=incident_id, summary="baseline failed to produce valid output",
                     abstain=True, abstain_reason="invalid output")
