import time

from agent import signals


def _prom(table):
    """Fake prom_query: choose a canned answer by substring of the PromQL text."""
    def fake(q):
        for key, rows in table.items():
            if key in q:
                return [{"metric": m, "value": [0, str(v)]} for m, v in rows]
        return []
    return fake


def test_cpu_saturation_flagged_only_against_baseline(monkeypatch):
    table = {
        "container_cpu_utilization_ratio[5m] offset": [({"container_name": "ad"}, 5), ({"container_name": "cart"}, 60)],
        "container_cpu_utilization_ratio[2m]": [({"container_name": "ad"}, 90), ({"container_name": "cart"}, 62)],
    }
    monkeypatch.setattr(signals.telemetry, "prom_query", _prom(table))
    kinds = {(a["kind"], a["service"]) for a in signals.resource_anomalies()}
    assert ("cpu_saturation", "ad") in kinds          # 5% -> 90%
    assert ("cpu_saturation", "cart") not in kinds    # always busy: not an anomaly


def test_standing_kafka_lag_is_noise_but_growth_is_not(monkeypatch):
    table = {
        "kafka_consumer_group_lag_sum_ratio offset": [({"group": "accounting"}, 50000), ({"group": "fraud-detection"}, 0)],
        "kafka_consumer_group_lag_sum_ratio": [({"group": "accounting"}, 50010), ({"group": "fraud-detection"}, 4000)],
        "kafka_consumer_group_members": [({"group": "accounting"}, 0), ({"group": "fraud-detection"}, 1)],
    }
    monkeypatch.setattr(signals.telemetry, "prom_query", _prom(table))
    found = {a["group"] for a in signals.resource_anomalies() if a["kind"] == "consumer_lag_growth"}
    assert found == {"fraud-detection"}


def test_memberless_group_lag_growth_is_not_reported(monkeypatch):
    # healthy-system behaviour of the demo's `accounting` group: no consumers, lag always growing
    table = {
        "kafka_consumer_group_lag_sum_ratio offset": [({"group": "accounting"}, 50000)],
        "kafka_consumer_group_lag_sum_ratio": [({"group": "accounting"}, 50300)],
        "kafka_consumer_group_members": [({"group": "accounting"}, 0)],
    }
    monkeypatch.setattr(signals.telemetry, "prom_query", _prom(table))
    assert signals.resource_anomalies() == []


def test_lost_consumer_group_members_detected(monkeypatch):
    table = {
        "kafka_consumer_group_members offset": [({"group": "fraud-detection"}, 1)],
        "kafka_consumer_group_members": [({"group": "fraud-detection"}, 0)],
    }
    monkeypatch.setattr(signals.telemetry, "prom_query", _prom(table))
    assert any(a["kind"] == "consumer_group_lost_members" for a in signals.resource_anomalies())


def test_metrics_outage_does_not_crash(monkeypatch):
    def boom(q):
        raise RuntimeError("prometheus down")
    monkeypatch.setattr(signals.telemetry, "prom_query", boom)
    assert signals.resource_anomalies() == []


def test_old_restart_count_is_not_reported(monkeypatch):
    old = "2020-01-01T00:00:00.000000000Z"
    new = time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime())
    rows = [
        {"service": "recommendation", "status": "running", "oom_killed": False, "exit_code": 0, "restart_count": 48,
         "started_at": old, "memory_limit_mb": 524, "cpu_limit": None},
        {"service": "email", "status": "running", "oom_killed": False, "exit_code": 0, "restart_count": 3,
         "started_at": new, "memory_limit_mb": 100, "cpu_limit": None},
    ]
    monkeypatch.setattr(signals.dockerctl, "container_states", lambda: rows)
    got = {c["service"] for c in signals.container_issues(since_ts=time.time() - 120)}
    assert got == {"email"}
