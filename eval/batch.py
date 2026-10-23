"""Unattended batch run that mimics a hidden test: for each scenario inject, alert, diagnose, (optionally)
approve+fix+verify, reset, cool down. Results append to data/results/<tag>.jsonl as they complete.

python -m eval.batch <tag> [--no-remediate] <scenario-or-group> ...
  groups: dev, heldout, flags (or any scenario name)
"""
from __future__ import annotations

import json
import sys
import time
import traceback

from eval.live import SCENARIOS, run
from tools import flagctl
from tools.config import ROOT


def quiesce(max_wait_s: int = 420, settle_s: int = 30) -> None:
    """Wait until the system is actually quiet before the next scenario.

    Services cache flag values for 2-3 minutes, so a reset fault keeps producing errors for a while; a fixed
    cooldown let one scenario's errors leak into the next. Quiet = no recent novel-looking error signatures
    and no resource anomalies (known standing noise is ignored).
    """
    from agent import signals
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            sigs = signals.error_signatures(list(signals.ENTRYPOINTS) + ["payment", "cart", "checkout"], minutes=2)
            real = [s for s in sigs if s["message"] and "Max retries exceeded" not in s["message"]]
            if not real and not signals.resource_anomalies():
                break
        except Exception:
            pass
        time.sleep(20)
    time.sleep(settle_s)


def expand(items: list[str]) -> list[str]:
    names: list[str] = []
    for it in items:
        names += [n for n, s in SCENARIOS.items() if s.group == it] or [it]
    return names


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    tag, remediate_it = args[0], "--no-remediate" not in args
    names = expand([a for a in args[1:] if not a.startswith("--")])
    out = ROOT / "data" / "results" / f"{tag}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    quiesce()  # start from a quiet system even if a previous run left a fault tail
    for i, name in enumerate(names):
        try:
            row = run(name, "--visible" not in args, remediate_it)  # --visible: flag/config state is readable
        except Exception as e:  # one bad scenario must not abort an unattended run; record it as invalid
            traceback.print_exc()
            row = {"scenario": name, "invalid": True, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            flagctl.reset_all()
        rows.append(row)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)
        if i < len(names) - 1:
            quiesce()
    valid = [r for r in rows if not r.get("invalid")]
    print(f"\n{tag}: {sum(r['action_correct'] for r in valid)}/{len(valid)} correct action, "
          f"{sum(r['abstained'] for r in valid)} abstained, {len(rows) - len(valid)} invalid, "
          f"recovered {sum(r.get('remediation') == 'recovered' for r in valid)}")
