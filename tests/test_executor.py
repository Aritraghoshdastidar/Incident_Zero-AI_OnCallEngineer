import json
from pathlib import Path

from agent import executor
from safety import AuditLog, KillSwitch, PolicyEngine, load_runbooks
from schema import ActionProposal, Diagnosis, Evidence, Hypothesis

RUNBOOKS = load_runbooks(Path(__file__).parent.parent / "runbooks")


def diag(action: ActionProposal | None) -> Diagnosis:
    h = Hypothesis(root_cause="x", service="payment", confidence=0.9,
                   evidence=[Evidence(kind="flag", ref="paymentFailure", summary="s")])
    return Diagnosis(incident_id="inc-t", summary="s", top=h, proposed_action=action)


def setup(tmp_path):
    return (PolicyEngine(RUNBOOKS, KillSwitch(tmp_path / "ks")), AuditLog(tmp_path / "audit.jsonl"))


def events(audit_path):
    return [json.loads(l)["event"] for l in audit_path.read_text().splitlines()]


GOOD = ActionProposal(runbook_id="disable_flag", params={"flag": "paymentFailure"}, rationale="r")


def test_rejection_never_executes(tmp_path, monkeypatch):
    engine, audit = setup(tmp_path)
    ran = []
    monkeypatch.setattr(executor, "_run", lambda argv: ran.append(argv))
    res = executor.remediate(diag(GOOD), engine, audit, approver=lambda card: False)
    assert res["status"] == "rejected" and ran == []
    assert "rejected" in events(tmp_path / "audit.jsonl")


def test_off_allowlist_action_never_reaches_approver(tmp_path, monkeypatch):
    engine, audit = setup(tmp_path)
    asked = []
    bad = ActionProposal(runbook_id="wipe_all", params={}, rationale="r")
    res = executor.remediate(diag(bad), engine, audit, approver=lambda c: asked.append(c) or True)
    assert res["status"] == "no_action" and asked == []


def test_kill_switch_blocks_even_approved_action(tmp_path):
    engine, audit = setup(tmp_path)
    KillSwitch(tmp_path / "ks").engage()
    res = executor.remediate(diag(GOOD), engine, audit, approver=lambda c: True)
    assert res["status"] == "no_action"


class Done:
    returncode, stdout, stderr = 0, "", ""


def _patch(monkeypatch, calls, verdict):
    monkeypatch.setattr(executor, "_run", lambda argv: calls.append(argv) or Done())
    monkeypatch.setattr(executor, "snapshot", lambda service: {"service": service})
    monkeypatch.setattr(executor, "verify_recovery", lambda *a, **k: verdict)


def test_worse_after_fix_triggers_exact_rollback(tmp_path, monkeypatch):
    engine, audit = setup(tmp_path)
    calls = []
    _patch(monkeypatch, calls, (False, {"residual_errors": [{}], "entrypoint_anomalies": [], "worse": True}))
    res = executor.remediate(diag(GOOD), engine, audit, approver=lambda c: True)
    assert res["status"] == "not_recovered_rolled_back"
    assert any("undo" in " ".join(c) for c in calls)  # rollback is the exact-undo command
    assert audit.verify()


def test_unconfirmed_but_not_worse_is_escalated_not_reverted(tmp_path, monkeypatch):
    # Reverting here would put the original fault back; a human should look instead.
    engine, audit = setup(tmp_path)
    calls = []
    _patch(monkeypatch, calls, (False, {"residual_errors": [], "entrypoint_anomalies": [], "worse": False}))
    res = executor.remediate(diag(GOOD), engine, audit, approver=lambda c: True)
    assert res["status"] == "not_recovered_escalate"
    assert not any("undo" in " ".join(c) for c in calls)
    assert "escalated" in events(tmp_path / "audit.jsonl")


def test_successful_fix_is_recorded_and_chain_intact(tmp_path, monkeypatch):
    engine, audit = setup(tmp_path)
    _patch(monkeypatch, [], (True, {"residual_errors": [], "entrypoint_anomalies": [], "worse": False}))
    res = executor.remediate(diag(GOOD), engine, audit, approver=lambda c: True)
    assert res["status"] == "recovered"
    assert events(tmp_path / "audit.jsonl")[-1] == "verified" and audit.verify()


def _health(p95):
    return {"payment": {"rps": 1.0, "error_rate": 0.0, "p95_ms": p95},
            "frontend": {"rps": 20.0, "error_rate": 0.0, "p95_ms": 4300.0}}


def test_noisy_frontend_latency_alone_does_not_block_recovery(monkeypatch):
    # The real false positive: frontend p95 swings 60 ms to 4 s by itself; errors were gone.
    monkeypatch.setattr(executor.signals, "error_signatures", lambda *a, **k: [])
    monkeypatch.setattr(executor.signals, "metric_anomalies", lambda *a, **k: [
        {"service": "frontend", "error_rate": 0.0, "baseline_error_rate": 0.0, "p95_ms": 4324.0,
         "baseline_p95_ms": 1685.0, "latency_ratio": 2.6, "score": 1.0}])
    monkeypatch.setattr(executor.signals, "_health", lambda w: _health(30.0))
    ok, detail = executor._check_once("payment", {"service": "payment", "latency_issue": False})
    assert ok and not detail["worse"]


def test_latency_fault_needs_the_diagnosed_service_to_improve(monkeypatch):
    monkeypatch.setattr(executor.signals, "error_signatures", lambda *a, **k: [])
    monkeypatch.setattr(executor.signals, "metric_anomalies", lambda *a, **k: [])
    pre = {"service": "currency", "latency_issue": True, "p95_ms": 2000.0, "baseline_p95_ms": 20.0}
    monkeypatch.setattr(executor.signals, "_health", lambda w: {"currency": {"rps": 1, "error_rate": 0, "p95_ms": 1900.0}})
    assert executor._check_once("currency", pre)[0] is False   # still slow: not recovered
    monkeypatch.setattr(executor.signals, "_health", lambda w: {"currency": {"rps": 1, "error_rate": 0, "p95_ms": 25.0}})
    assert executor._check_once("currency", pre)[0] is True    # back to normal


def test_new_errors_after_fix_are_flagged_as_worse(monkeypatch):
    new = {"service": "cart", "op": "X", "message": "boom", "count": 3, "example_trace": "t"}
    monkeypatch.setattr(executor.signals, "error_signatures", lambda *a, **k: [dict(new)])
    monkeypatch.setattr(executor.signals, "metric_anomalies", lambda *a, **k: [])
    monkeypatch.setattr(executor.signals, "_health", lambda w: {})
    ok, detail = executor._check_once("payment", {"service": "payment", "error_keys": []})
    assert not ok and detail["worse"]
    pre = {"service": "payment", "error_keys": [list(executor.signals._sig_key(new))]}
    assert executor._check_once("payment", pre)[1]["worse"] is False  # same error as before the fix


def test_tampered_audit_log_is_detected(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.append("a", "i"); audit.append("b", "i")
    p = tmp_path / "audit.jsonl"
    p.write_text(p.read_text().replace('"event": "a"', '"event": "z"'))
    assert not AuditLog(p).verify()
