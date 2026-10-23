"""Remediation pipeline: policy check -> decision card -> human approval -> dry run -> execute ->
verify recovery -> auto-rollback on failure. Every step is written to the audit log.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable

from safety import AuditLog, PolicyEngine
from schema import Diagnosis
from tools.config import DOCKER, ROOT

from . import signals


@dataclass
class DecisionCard:
    incident_id: str
    root_cause: str
    confidence: float
    grounding: float | None
    runbook_id: str
    params: dict
    risk: str
    command: list[str]
    dry_run_command: list[str] | None
    rollback_command: list[str] | None
    evidence: list[str]

    def render(self) -> str:
        lines = [
            f"INCIDENT {self.incident_id}",
            f"Root cause : {self.root_cause}  (confidence {self.confidence:.2f}, grounding {self.grounding})",
            "Evidence   : " + " | ".join(self.evidence[:3]),
            f"Proposed   : {self.runbook_id} {self.params}  [risk: {self.risk}]",
            f"Will run   : {' '.join(self.command)}",
            f"Rollback   : {' '.join(self.rollback_command) if self.rollback_command else 'none (restart is idempotent)'}",
        ]
        return "\n".join(lines)


Approver = Callable[[DecisionCard], bool]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    argv = list(argv)
    if argv[0] == "python":
        argv[0] = sys.executable
    elif argv[0] == "docker":
        argv[0] = DOCKER
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120)


def build_card(d: Diagnosis, engine: PolicyEngine) -> tuple[DecisionCard | None, str]:
    if d.abstain or d.proposed_action is None or d.top is None:
        return None, "no action proposed"
    decision = engine.evaluate(d.proposed_action)
    if not decision.allowed:
        return None, f"policy rejected: {decision.reason}"
    rb, p = decision.runbook, d.proposed_action.params
    return DecisionCard(
        incident_id=d.incident_id, root_cause=d.top.root_cause, confidence=d.top.confidence,
        grounding=d.grounding, runbook_id=rb.id, params=p, risk=rb.risk,
        command=engine.render_argv(rb, p),
        dry_run_command=engine.render_argv(rb, p, dry_run=True) if rb.dry_run_argv else None,
        rollback_command=[x.format(**{k: str(v) for k, v in p.items()}) for x in rb.rollback_argv]
        if rb.rollback_argv else None,
        evidence=[f"{e.kind}:{e.ref}" for e in d.top.evidence],
    ), "ok"


def _real(sigs: list[dict]) -> list[dict]:
    # Ignore standing noise that pre-dates any incident (e.g. the load generator calling an undeployed service).
    return [s for s in sigs if s["message"] and "Max retries exceeded" not in s["message"]]


def snapshot(service: str) -> dict:
    """The system just before the fix. Recovery is judged against this, not against a noisy baseline:
    frontend p95 alone swings between ~60 ms and ~4 s on a laptop, so a fixed latency ratio is not evidence."""
    watch = list(dict.fromkeys([service, *signals.ENTRYPOINTS]))
    a = next((x for x in signals.metric_anomalies(window="2m") if x["service"] == service), None)
    keys = {signals._sig_key(s) for s in _real(signals.error_signatures(watch, minutes=2))}
    return {"service": service, "latency_issue": bool(a and a["latency_ratio"] >= 2.0),
            "p95_ms": a["p95_ms"] if a else None, "baseline_p95_ms": a["baseline_p95_ms"] if a else None,
            "error_keys": sorted(map(list, keys))}


def _check_once(service: str, pre: dict) -> tuple[bool, dict]:
    watch = list(dict.fromkeys([service, *signals.ENTRYPOINTS]))
    real = _real(signals.error_signatures(watch, minutes=1))
    # Entry-point ERROR rate only. 2m window: span metrics are exported too sparsely for rate() over 1m.
    err_anoms = [a for a in signals.metric_anomalies(window="2m")
                 if a["service"] in signals.ENTRYPOINTS and a["error_rate"] - a["baseline_error_rate"] > 0.01]
    latency_ok = True
    if pre.get("latency_issue"):  # latency counts only if the diagnosed service had a latency problem to fix
        now = signals._health("2m").get(service)
        limit = max(1.5 * (pre.get("baseline_p95_ms") or 0), 0.6 * (pre.get("p95_ms") or 0))
        latency_ok = bool(now) and now["p95_ms"] <= limit
    pre_keys = {tuple(k) for k in pre.get("error_keys", [])}
    worse = any(signals._sig_key(s) not in pre_keys for s in real)  # errors the fix did not start with
    ok = not real and not err_anoms and latency_ok
    return ok, {"residual_errors": real[:3], "entrypoint_anomalies": err_anoms, "latency_ok": latency_ok,
                "worse": worse}


def verify_recovery(service: str, pre: dict, timeout_s: int = 300, interval_s: int = 20,
                    need_clean: int = 2) -> tuple[bool, dict]:
    """Poll until `need_clean` consecutive clean checks, or time out.

    Config changes take time to propagate (services cache flag values), so a fixed sleep gives
    false negatives. Clean checks only count while the entrypoints still receive traffic, so
    'no errors because nothing is happening' is not mistaken for recovery.
    """
    deadline, clean, detail = time.time() + timeout_s, 0, {}
    while time.time() < deadline:
        time.sleep(interval_s)
        ok, detail = _check_once(service, pre)
        traffic = any(v["rps"] > 0.05 for s, v in signals._health("2m").items() if s in signals.ENTRYPOINTS)
        clean = clean + 1 if (ok and traffic) else 0
        if clean >= need_clean:
            return True, detail
    return False, detail


def remediate(d: Diagnosis, engine: PolicyEngine, audit: AuditLog, approver: Approver,
              timeout_s: int = 300) -> dict:
    card, why = build_card(d, engine)
    if card is None:
        audit.append("no_action", d.incident_id, reason=why)
        return {"status": "no_action", "reason": why}
    audit.append("decision_card", d.incident_id, card=card.__dict__)
    if not approver(card):
        audit.append("rejected", d.incident_id)
        return {"status": "rejected"}
    audit.append("approved", d.incident_id)
    pre = snapshot(d.top.service)
    audit.append("pre_fix_snapshot", d.incident_id, **pre)
    if card.dry_run_command:
        dry = _run(card.dry_run_command)
        audit.append("dry_run", d.incident_id, rc=dry.returncode, out=dry.stdout[:300])
    res = _run(card.command)
    audit.append("executed", d.incident_id, rc=res.returncode, out=res.stdout[:300], err=res.stderr[:300])
    if res.returncode != 0:
        return {"status": "failed", "error": res.stderr[:300]}
    ok, detail = verify_recovery(d.top.service, pre, timeout_s)
    audit.append("verified", d.incident_id, recovered=ok, **detail)
    if ok:
        return {"status": "recovered", **detail}
    # Roll back only if the fix made things worse. Reverting a fix that merely could not be confirmed
    # would put the original fault back, so in that case leave the fix in place and hand it to a human.
    if detail.get("worse") and card.rollback_command:
        rb = _run(card.rollback_command)
        audit.append("rolled_back", d.incident_id, rc=rb.returncode)
        return {"status": "not_recovered_rolled_back", **detail}
    audit.append("escalated", d.incident_id, reason="recovery not confirmed; fix left in place for human review")
    return {"status": "not_recovered_escalate", **detail}
