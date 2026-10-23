"""Build site/data.js from REAL recorded runs: Prometheus history, the audit log, and the results files.

python site/build_data.py        (needs the demo stack up; Prometheus keeps the metrics from earlier runs)

Nothing here is invented. The only inferred value is the fault-injection time: the evaluation harness injects
a fault, sleeps `develop` seconds, then investigates, so injection = bundle_built - develop.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROM = "http://127.0.0.1:9090"


def rate(svc, extra=""):
    return f'sum(rate(traces_span_metrics_calls_total{{service_name="{svc}"{extra}}}[2m]))'


ERROR_LABEL = ',status_code="STATUS_CODE_ERROR"'


def err_pct(svc):
    return f"100 * {rate(svc, ERROR_LABEL)} / {rate(svc)}"


def p95(svc):
    return ('histogram_quantile(0.95, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket'
            f'{{service_name="{svc}"}}[2m])))')


def cpu(c):
    return f'avg(container_cpu_utilization_ratio{{container_name="{c}"}})'


def mem(c):
    return f'avg(container_memory_percent_ratio{{container_name="{c}"}})'


# id, incident, develop seconds, plain title, what was broken, series (label, promql, unit, pen)
SCENARIOS = [
    dict(id="payment", incident="inc-e0101d9c", develop=100, flag_visible=True,
         title="Customers can't pay",
         alert="Customers cannot complete payment at checkout",
         broken="The paymentFailure feature flag was switched to 100%.",
         series=[("payment errors", err_pct("payment"), "%", "alarm"), ("checkout errors", err_pct("checkout"), "%", "ref")]),
    dict(id="ad_cpu", incident="inc-f29ee63e", develop=100, flag_visible=True,
         title="The ad service is overloaded",
         alert="Frontend latency is high and the ad service looks overloaded",
         broken="The adHighCpu feature flag was switched on.",
         series=[("ad CPU", cpu("ad"), "%", "alarm"), ("ad p95 latency", p95("ad"), "ms", "ref")]),
    dict(id="redis", incident="inc-e0d790de", develop=200, flag_visible=False,
         title="Cart storage went down",
         alert="Checkout error rate elevated, customers report failed orders",
         broken="The valkey-cart container was stopped. No feature flag was involved.",
         series=[("checkout errors", err_pct("checkout"), "%", "alarm"),
                 ("valkey-cart uptime", 'container_uptime_seconds{container_name="valkey-cart"}', "s", "ref")]),
    dict(id="catalog", incident="inc-21f8bcaf", develop=120, flag_visible=False,
         title="Product pages won't load",
         alert="Product pages are failing to load for customers",
         broken="The product-catalog container was stopped.",
         series=[("frontend errors", err_pct("frontend"), "%", "alarm"), ("catalog requests", rate("product-catalog"), "/s", "ref")]),
    dict(id="cpu", incident="inc-b8acaec3", develop=150, flag_visible=False,
         title="Checkout is slow",
         alert="Checkout is slow, currency conversion looks sluggish",
         broken="The currency container was limited to 0.02 CPU.",
         series=[("currency p95 latency", p95("currency"), "ms", "alarm"), ("currency CPU", cpu("currency"), "%", "ref")]),
    dict(id="oom", incident="inc-435183ca", develop=150, flag_visible=False,
         title="Recommendations keep disappearing",
         alert="Product recommendations are intermittently missing on the storefront",
         broken="The recommendation container was limited to 20 MB of memory.",
         series=[("recommendation memory", mem("recommendation"), "%", "alarm"),
                 ("recommendation requests", rate("recommendation"), "/s", "ref")]),
    dict(id="healthy", incident="inc-279c61f6", develop=60, flag_visible=False,
         title="Nothing is wrong",
         alert="Latency alert fired on the storefront, please investigate",
         broken="Nothing. This is a false alarm on a healthy system.",
         series=[("checkout errors", err_pct("checkout"), "%", "alarm"), ("frontend p95 latency", p95("frontend"), "ms", "ref")]),
]

STEP_LABELS = {
    "bundle_built": "Built the evidence bundle",
    "tool_call": "Looked closer",
    "diagnosis": "Diagnosed",
    "decision_card": "Asked for approval",
    "approved": "Approved",
    "dry_run": "Dry run",
    "pre_fix_snapshot": "Recorded the state before the fix",
    "executed": "Ran the fix",
    "verified": "Checked recovery",
    "rolled_back": "Rolled back",
    "escalated": "Escalated to a human",
    "rejected": "Rejected",
}


def prom_range(q, t0, t1, step=15):
    r = httpx.get(f"{PROM}/api/v1/query_range", params={"query": q, "start": t0, "end": t1, "step": step}, timeout=60)
    res = r.json()["data"]["result"]
    if not res:
        return []
    return [[round(float(t) - t0), None if v == "NaN" else round(float(v), 3)] for t, v in res[0]["values"]]


def load_audit():
    rows = []
    for f in ("audit.jsonl", "eval.jsonl"):
        p = ROOT / "data" / "audit" / f
        rows += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    by: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        by.setdefault(r["incident_id"], []).append(r)
    return by


def build_scenario(spec, audit):
    ev = audit[spec["incident"]]
    bundle_ts = next(e["ts"] for e in ev if e["event"] == "bundle_built")
    inject = bundle_ts - spec["develop"]
    t0 = inject - 120
    t1 = ev[-1]["ts"] + 150
    events = [{"t": round(inject - t0), "kind": "fault", "label": "Fault injected", "detail": spec["broken"]}]
    card = None
    for e in ev:
        k, d = e["event"], e["data"]
        if k not in STEP_LABELS or k in ("approver",):
            continue
        item = {"t": round(e["ts"] - t0), "kind": k, "label": STEP_LABELS[k]}
        if k == "tool_call":
            item["detail"] = f'{d.get("tool")} {d.get("args")}'
        elif k == "bundle_built":
            item["detail"] = f'{d.get("anomalies", 0)} services with metric anomalies'
        elif k == "diagnosis":
            item["detail"] = d.get("root_cause") or "No confident root cause; abstained."
            item["confidence"], item["grounding"], item["abstain"] = d.get("confidence"), d.get("grounding"), d.get("abstain")
        elif k == "decision_card":
            card = d["card"]
            item["detail"] = " ".join(card["command"])
        elif k == "executed":
            item["detail"] = "exit code " + str(d.get("rc"))
        elif k == "verified":
            item["detail"] = "recovered" if d.get("recovered") else "not confirmed"
            item["recovered"] = bool(d.get("recovered"))
        events.append(item)
    series = []
    for label, q, unit, pen in spec["series"]:
        series.append({"label": label, "unit": unit, "pen": pen, "points": prom_range(q, t0, t1)})
    return {"id": spec["id"], "title": spec["title"], "alert": spec["alert"], "broken": spec["broken"],
            "flagVisible": spec["flag_visible"], "duration": round(t1 - t0), "events": events, "series": series,
            "card": card}


def load_results():
    out = {"ablation": [], "redteam": [], "heldout": [], "development": []}
    ab = ROOT / "data" / "results" / "ablation.jsonl"
    out["ablation"] = [json.loads(line) for line in ab.read_text(encoding="utf-8").splitlines() if line.strip()]
    rt = ROOT / "data" / "results" / "redteam.json"
    if rt.exists():
        out["redteam"] = json.loads(rt.read_text(encoding="utf-8"))
    for name, key in (("hidden_sim", "development"), ("rerun_blind", "development"), ("rerun2_blind", "development"),
                      ("confirm_blind", "development"), ("visible", "development")):
        p = ROOT / "data" / "results" / f"{name}.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    row["run"] = name
                    out[key].append(row)
    return out


def load_runbooks():
    books = []
    for f in sorted((ROOT / "runbooks").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        books.append({"id": d["id"], "description": d["description"], "risk": d["risk"],
                      "requiresApproval": d.get("requires_approval", True),
                      "params": {k: {"type": v["type"], "allowed": v["allowed"]} for k, v in d.get("params", {}).items()},
                      "argv": d["argv"]})
    return books


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    audit = load_audit()
    scenarios = []
    for spec in SCENARIOS:
        s = build_scenario(spec, audit)
        scenarios.append(s)
        pts = [len(x["points"]) for x in s["series"]]
        print(f'{s["id"]:8} {s["duration"]:4}s  events={len(s["events"])}  points={pts}')
    attacks = []
    try:
        sys.path.insert(0, str(ROOT))
        from eval.redteam import ATTACKS
        attacks = [{"id": k, "text": v} for k, v in ATTACKS.items()]
    except Exception as e:  # the site still builds without the attack presets
        print("red-team presets unavailable:", e)
    data = {"builtAt": time.strftime("%Y-%m-%d", time.gmtime()), "scenarios": scenarios, "results": load_results(),
            "runbooks": load_runbooks(), "attacks": attacks}
    out = Path(__file__).resolve().parent / "data.js"
    out.write_text("window.INCIDENT_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("wrote", out, f"{out.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
