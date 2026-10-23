from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from safety import KillSwitch, PolicyEngine, load_runbooks
from schema import ActionProposal

RUNBOOKS = load_runbooks(Path(__file__).parent.parent / "runbooks")


@pytest.fixture
def engine(tmp_path):
    return PolicyEngine(RUNBOOKS, KillSwitch(tmp_path / "ks"))


def prop(rid, **params):
    return ActionProposal(runbook_id=rid, params=params, rationale="t")


def test_allows_valid_runbook(engine):
    d = engine.evaluate(prop("disable_flag", flag="cartFailure"))
    assert d.allowed and d.needs_approval


def test_rejects_unknown_runbook(engine):
    assert not engine.evaluate(prop("rm_rf")).allowed


def test_rejects_param_outside_allowlist(engine):
    assert not engine.evaluate(prop("restart_service", service="ad; rm -rf /")).allowed


def test_rejects_extra_or_missing_params(engine):
    assert not engine.evaluate(prop("disable_flag", flag="cartFailure", extra="x")).allowed
    assert not engine.evaluate(prop("disable_flag")).allowed


def test_kill_switch_blocks_everything(tmp_path):
    ks = KillSwitch(tmp_path / "ks")
    eng = PolicyEngine(RUNBOOKS, ks)
    ks.engage()
    assert not eng.evaluate(prop("disable_flag", flag="cartFailure")).allowed


def test_medium_risk_always_needs_approval(engine):
    assert engine.evaluate(prop("restart_service", service="cart")).needs_approval


@given(st.text(max_size=80))
def test_fuzz_flag_param_never_escapes_allowlist(value):
    eng = PolicyEngine(RUNBOOKS, KillSwitch(Path("nonexistent-ks")))
    d = eng.evaluate(prop("disable_flag", flag=value))
    allowed_flags = RUNBOOKS["disable_flag"].params["flag"].allowed
    assert d.allowed == (value in allowed_flags)
