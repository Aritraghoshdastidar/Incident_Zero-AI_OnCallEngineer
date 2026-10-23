import time

from agent import signals


def sig(service, op, msg, count):
    return {"service": service, "op": op, "message": msg, "count": count, "example_trace": "t"}


def _quiet(monkeypatch):
    monkeypatch.setattr(signals, "metric_anomalies", lambda *a, **k: [])
    monkeypatch.setattr(signals, "container_issues", lambda *a, **k: [])
    monkeypatch.setattr(signals, "resource_anomalies", lambda *a, **k: [])


def test_novel_signatures_rank_before_louder_pre_existing_noise(monkeypatch):
    noise = sig("load-generator", "POST", "ConnectionError agent:8010", 19)
    real = sig("cart", "EmptyCart", "Can't access cart storage", 2)

    def fake_sigs(services, minutes=5, end_ago_min=0.0):
        # the baseline window (shifted into the past) only contains the noise
        return [dict(noise)] if end_ago_min else [dict(noise), dict(real)]

    _quiet(monkeypatch)
    monkeypatch.setattr(signals, "error_signatures", fake_sigs)
    monkeypatch.setattr(signals.flagctl, "active", lambda: {})
    b = signals.build_bundle(blind=True, since_ts=None)
    assert b["error_signatures"][0]["service"] == "cart"
    assert b["error_signatures"][0]["pre_existing"] is False
    assert b["error_signatures"][1]["pre_existing"] is True


def test_blind_bundle_hides_config_state(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(signals, "error_signatures", lambda *a, **k: [])
    monkeypatch.setattr(signals.flagctl, "active", lambda: {"cartFailure": "100%"})
    assert "active_config_overrides" not in signals.build_bundle(blind=True)
    assert signals.build_bundle(blind=False)["active_config_overrides"] == {"cartFailure": "100%"}


def test_window_has_five_minute_floor(monkeypatch):
    seen = []
    _quiet(monkeypatch)
    monkeypatch.setattr(signals, "error_signatures", lambda s, m=5, end_ago_min=0.0: seen.append(m) or [])
    signals.build_bundle(blind=True, since_ts=time.time() - 30)  # alert fired 30s ago
    assert seen[0] >= 5
