"""Paired ablation: for each scenario inject ONE fault, then run both the hybrid agent and the naive
baseline against that same live system state, and score both identically. Diagnosis only (no remediation).

python -m eval.ablation [scenario ...]    -> data/results/ablation.jsonl (+ summary table)
"""
from __future__ import annotations

import json
import sys
import time

from agent.investigator import investigate
from agent.llm import LLM
from eval import baseline
from eval.live import SCENARIOS
from safety import AuditLog
from tools import flagctl
from tools.config import ROOT

OUT = ROOT / "data" / "results" / "ablation.jsonl"


def score(sc, diag, llm: LLM, seconds: float) -> dict:
    action = diag.proposed_action
    return {"abstained": diag.abstain,
            "service_correct": (diag.top is None or diag.abstain) if sc.expect_no_action
            else bool(diag.top) and diag.top.service == sc.service,
            "action_correct": (action is None) if sc.expect_no_action
            else bool(action) and sc.fix_param in map(str, action.params.values()),
            # a confident wrong action is the failure that matters most (any action on a healthy system is wrong)
            "wrong_action": bool(action) and (sc.expect_no_action or sc.fix_param not in map(str, action.params.values())),
            "confidence": diag.top.confidence if diag.top else None, "grounding": diag.grounding,
            "root_cause": diag.top.root_cause if diag.top else None,
            "seconds": round(seconds, 1), "tokens": llm.usage.prompt_tokens + llm.usage.completion_tokens}


def run_one(name: str) -> dict:
    sc = SCENARIOS[name]
    sc.reset(); flagctl.reset_all()
    sc.inject()
    since = time.time()
    print(f"[{name}] injected; developing {sc.develop_s}s", flush=True)
    time.sleep(sc.develop_s)
    out = {"scenario": name, "group": sc.group}
    try:
        llm = LLM(); t = time.time()
        d = investigate(sc.alert, llm, AuditLog(ROOT / "data" / "audit" / "ablation.jsonl"), blind=True, since_ts=since)
        out["hybrid"] = score(sc, d, llm, time.time() - t)
        llm = LLM(); t = time.time()
        d = baseline.diagnose(sc.alert, llm)
        out["baseline"] = score(sc, d, llm, time.time() - t)
    finally:
        sc.reset()
    return out


def summarize(rows: list[dict]) -> str:
    def agg(key):
        rs = [r[key] for r in rows if key in r]
        n = len(rs)
        return (f"{sum(r['action_correct'] for r in rs)}/{n} correct, {sum(r['abstained'] for r in rs)} abstained, "
                f"{sum(r['wrong_action'] for r in rs)} wrong actions, "
                f"avg {sum(r['seconds'] for r in rs) / n:.0f}s, avg {sum(r['tokens'] for r in rs) / n:.0f} tokens")
    return f"hybrid  : {agg('hybrid')}\nbaseline: {agg('baseline')}"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    names = sys.argv[1:] or list(SCENARIOS)
    rows = []
    for i, n in enumerate(names):
        r = run_one(n)
        rows.append(r)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")
        brief = ("action_correct", "abstained", "wrong_action", "confidence", "seconds")
        print(json.dumps({k: (v if not isinstance(v, dict) else {kk: v[kk] for kk in brief})
                          for k, v in r.items()}), flush=True)
        if i < len(names) - 1:
            time.sleep(120)  # cooldown so one scenario's errors cannot leak into the next
    print("\n" + summarize(rows))
