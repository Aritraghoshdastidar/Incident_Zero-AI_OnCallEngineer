"""Deterministic signal detectors: turn raw telemetry into a compact evidence bundle.

The LLM reasons over this bundle (plus targeted drill-down tools) instead of raw dumps,
which keeps prompts small, reduces hallucination and makes weaker models usable.
"""
from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from tools import dockerctl, flagctl, telemetry

ENTRYPOINTS = ("frontend", "checkout")


def _health(window: str, offset: str = "") -> dict[str, dict]:
    off = f" offset {offset}" if offset else ""
    calls = "traces_span_metrics_calls_total"
    total = {r["metric"]["service_name"]: float(r["value"][1])
             for r in telemetry.prom_query(f"sum by (service_name) (rate({calls}[{window}]{off}))")}
    err = {r["metric"]["service_name"]: float(r["value"][1])
           for r in telemetry.prom_query(
               f'sum by (service_name) (rate({calls}{{status_code="STATUS_CODE_ERROR"}}[{window}]{off}))')}
    p95 = {r["metric"]["service_name"]: float(r["value"][1])
           for r in telemetry.prom_query(
               "histogram_quantile(0.95, sum by (le, service_name) "
               f"(rate(traces_span_metrics_duration_milliseconds_bucket[{window}]{off})))")
           if r["value"][1] != "NaN"}
    return {s: {"rps": rate, "error_rate": err.get(s, 0.0) / rate if rate else 0.0, "p95_ms": p95.get(s, 0.0)}
            for s, rate in total.items()}


def metric_anomalies(window: str = "2m", baseline_offset: str = "15m") -> list[dict]:
    """Per-service deltas against its own recent baseline, ranked by severity."""
    now, base = _health(window), _health("5m", baseline_offset)
    out = []
    for svc, cur in now.items():
        b = base.get(svc, {"error_rate": 0.0, "p95_ms": 0.0})
        d_err = cur["error_rate"] - b["error_rate"]
        ratio = cur["p95_ms"] / b["p95_ms"] if b["p95_ms"] > 1 else 1.0
        score = max(d_err * 20, 0) + max(min(ratio, 50) - 1.5, 0)
        if d_err > 0.01 or ratio > 2.0:
            out.append({"service": svc, "error_rate": round(cur["error_rate"], 4),
                        "baseline_error_rate": round(b["error_rate"], 4),
                        "p95_ms": round(cur["p95_ms"], 1), "baseline_p95_ms": round(b["p95_ms"], 1),
                        "latency_ratio": round(ratio, 1), "score": round(score, 2)})
    return sorted(out, key=lambda a: -a["score"])


def error_signatures(services: list[str], minutes: int = 5, end_ago_min: float = 0.0) -> list[dict]:
    """Cluster error spans across traces by (service, operation, message), most frequent first."""
    def scan(svc: str) -> list[dict]:
        try:
            return telemetry.jaeger_error_traces(svc, minutes, limit=40, end_ago_min=end_ago_min)
        except Exception:
            return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(scan, services))
    sigs: Counter = Counter()
    example: dict = {}
    for traces in results:
        for t in traces:
            for e in t["error_spans"]:
                key = (e["service"], e["op"], " ".join(e["message"].split())[:140])
                sigs[key] += 1
                example.setdefault(key, t["trace_id"])
    return [{"service": s, "op": o, "message": m, "count": c, "example_trace": example[(s, o, m)]}
            for (s, o, m), c in sigs.most_common(12)]


def _started_after(started_at: str, since_ts: float) -> bool:
    from datetime import datetime, timezone
    ts = datetime.fromisoformat(started_at[:19]).replace(tzinfo=timezone.utc).timestamp()
    return ts >= since_ts


def _by(query: str, label: str) -> dict[str, float]:
    return {r["metric"].get(label, "?"): float(r["value"][1]) for r in telemetry.prom_query(query)
            if r["value"][1] not in ("NaN", "+Inf")}


def resource_anomalies(base_offset: str = "15m") -> list[dict]:
    """Resource saturation and queue growth, always as CHANGE against the system's own baseline.

    Absolute values mislead: some demo consumers sit permanently at high lag / zero members when healthy.
    """
    out: list[dict] = []
    try:
        cpu_now = _by("avg_over_time(container_cpu_utilization_ratio[2m])", "container_name")
        cpu_base = _by(f"avg_over_time(container_cpu_utilization_ratio[5m] offset {base_offset})", "container_name")
        for c, now in cpu_now.items():
            base = cpu_base.get(c, 0.0)
            if now >= 30 and now >= 3 * max(base, 1.0):
                out.append({"kind": "cpu_saturation", "service": c, "now_pct": round(now, 1), "baseline_pct": round(base, 1)})
        mem_now = _by("avg_over_time(container_memory_percent_ratio[2m])", "container_name")
        mem_base = _by(f"avg_over_time(container_memory_percent_ratio[5m] offset {base_offset})", "container_name")
        for c, now in mem_now.items():
            base = mem_base.get(c, 0.0)
            if now >= 85 and now - base >= 20:
                out.append({"kind": "memory_pressure", "service": c, "now_pct": round(now, 1), "baseline_pct": round(base, 1)})
        # Queues build quickly but slowly in absolute terms at demo load: compare with 5 minutes ago, low threshold.
        lag_now = _by("kafka_consumer_group_lag_sum_ratio", "group")
        lag_base = _by("kafka_consumer_group_lag_sum_ratio offset 5m", "group")
        mem_g = _by("kafka_consumer_group_members", "group")
        mem_g_base = _by(f"kafka_consumer_group_members offset {base_offset}", "group")
        for g, now in lag_now.items():
            grew = now - lag_base.get(g, 0.0)
            # Only a group with live consumers can "fall behind". A group with no members at all (the demo's
            # `accounting`) grows lag forever when healthy; losing members is reported separately below.
            if grew >= 20 and mem_g.get(g, 0) >= 1:
                out.append({"kind": "consumer_lag_growth", "group": g, "lag_now": int(now), "lag_growth": int(grew)})
        for g, now in mem_g.items():
            if mem_g_base.get(g, 0) >= 1 and now < 1:
                out.append({"kind": "consumer_group_lost_members", "group": g, "members_now": int(now)})
    except Exception:  # a metrics outage must not take down the investigation
        pass
    return out


def container_issues(since_ts: float | None = None) -> list[dict]:
    """Infra state an on-call engineer would check first: stopped/killed/restarting containers and any
    CPU limit set (the demo sets none by default, so one is notable)."""
    out = []
    for c in dockerctl.container_states():
        reasons = []
        if c["status"] != "running":
            reasons.append(f"status={c['status']} exit_code={c['exit_code']}")
        if c["oom_killed"]:
            reasons.append("oom_killed")
        # Restarts only count if the container (re)started inside the incident window: an earlier test's
        # leftover restart count is history, not news.
        if c["restart_count"] > 0 and since_ts and _started_after(c["started_at"], since_ts - 60):
            reasons.append(f"restarts={c['restart_count']}")
        if c["cpu_limit"]:
            reasons.append(f"cpu_limit={c['cpu_limit']}")
        if reasons:
            out.append({"service": c["service"], "issues": reasons, "memory_limit_mb": c["memory_limit_mb"]})
    return out


def _sig_key(s: dict) -> tuple:
    return (s["service"], s["op"], s["message"][:60])


def build_bundle(blind: bool = False, since_ts: float | None = None) -> dict:
    """blind=True withholds config/flag state, so evaluation can't be solved by reading the answer.

    since_ts is when the alert started (a real pager provides this). Errors inside the incident window
    are compared with a baseline window just before it: signatures that already existed are tagged
    `pre_existing` (likely background noise) and ranked after genuinely novel ones.
    """
    anomalies = metric_anomalies()
    suspects = [a["service"] for a in anomalies[:5]]
    scan = list(dict.fromkeys([*suspects, *ENTRYPOINTS]))
    since_ts = since_ts or time.time() - 300
    # Floor of 5 min: faults on low-traffic paths (e.g. cart EmptyCart ~2 errors/5min) leave no samples in
    # shorter windows. Baseline-novelty tagging below is what keeps the longer window from drowning in noise.
    window = min(max(int((time.time() - since_ts) / 60) + 1, 5), 10)
    current = error_signatures(scan, window)
    baseline_keys = {_sig_key(s) for s in error_signatures(scan, 10, end_ago_min=window + 1)}
    for s in current:
        s["pre_existing"] = _sig_key(s) in baseline_keys
    current.sort(key=lambda s: (s["pre_existing"], -s["count"]))
    bundle = {
        "incident_window_minutes": window,
        "metric_anomalies": anomalies[:8],
        "error_signatures": current,
        "resource_anomalies": resource_anomalies(),
        "container_issues": container_issues(since_ts),
    }
    if not blind:
        bundle["active_config_overrides"] = flagctl.active()
    return bundle
