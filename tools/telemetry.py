"""Read-only telemetry tools. Everything returned here is UNTRUSTED data (it can contain
text planted by an attacker in logs/traces) and is passed to the LLM only inside a
clearly delimited data block, never as instructions.
"""
from __future__ import annotations

import json
import subprocess
import time

import httpx

from .config import DOCKER, JAEGER_URL, PROMETHEUS_URL

_client = httpx.Client(timeout=15.0)


def prom_query(promql: str) -> list[dict]:
    r = _client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql})
    r.raise_for_status()
    return r.json()["data"]["result"]


def _attr(span: dict, key: str):
    for a in span.get("attributes", []):
        if a["key"] == key:
            return next(iter(a["value"].values()))
    return None


def jaeger_error_traces(service: str, minutes: int = 10, limit: int = 20, end_ago_min: float = 0.0) -> list[dict]:
    """Recent traces touching `service` that contain an ERROR span, as compact summaries.

    Jaeger v2 only serves the v3 API (OTLP JSON, newline-delimited chunks).
    """
    now = time.time() - end_ago_min * 60  # window is [now-minutes, now], optionally shifted into the past
    fmt = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    r = _client.get(
        f"{JAEGER_URL}/api/v3/traces",
        params={
            "query.service_name": service,
            "query.start_time_min": fmt(now - minutes * 60),
            "query.start_time_max": fmt(now),
            "query.search_depth": 200,
        },
        timeout=40.0,
    )
    r.raise_for_status()
    traces: dict[str, list[dict]] = {}
    for line in r.text.splitlines():
        if not line.strip():
            continue
        for rs in json.loads(line).get("result", {}).get("resourceSpans", []):
            svc = next((a["value"]["stringValue"] for a in rs["resource"]["attributes"] if a["key"] == "service.name"), "?")
            for ss in rs["scopeSpans"]:
                for sp in ss["spans"]:
                    sp["_svc"] = svc
                    traces.setdefault(sp["traceId"], []).append(sp)
    out = []
    cutoff_ns = (now - minutes * 60) * 1e9
    for tid, spans in traces.items():
        # Jaeger returns whole traces that touch the window; the load generator keeps one trace open for
        # a whole user session (minutes), so filter on each span's own start time or stale errors leak in.
        bad = [
            {"service": s["_svc"], "op": s["name"], "message": s.get("status", {}).get("message", "")[:200],
             "grpc_status": _attr(s, "rpc.grpc.status_code")}
            for s in spans
            if s.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR")
            and cutoff_ns <= int(s["startTimeUnixNano"]) <= now * 1e9
        ]
        if bad:
            out.append({"trace_id": tid, "spans": len(spans), "error_spans": bad[:6]})
    return out[:limit]


def container_logs(container: str, tail: int = 100) -> list[str]:
    out = subprocess.run([DOCKER, "logs", "--tail", str(tail), container], capture_output=True, text=True)
    return (out.stdout + out.stderr).splitlines()[-tail:]
