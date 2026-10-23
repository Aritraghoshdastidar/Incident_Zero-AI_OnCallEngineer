"""Human-in-the-loop approver backed by files, so the agent process and the dashboard are decoupled.

The agent writes a pending decision card; the dashboard shows it; a human clicks Approve/Reject, which
writes a decision file. No decision before the timeout means REJECT (fail closed).
"""
from __future__ import annotations

import json
import time

from tools.config import ROOT

PENDING = ROOT / "data" / "pending"
DECISIONS = ROOT / "data" / "decisions"


def file_approver(card, timeout_s: int = 900, poll_s: float = 1.0, audit=None) -> bool:
    PENDING.mkdir(parents=True, exist_ok=True)
    DECISIONS.mkdir(parents=True, exist_ok=True)
    (PENDING / f"{card.incident_id}.json").write_text(
        json.dumps({**card.__dict__, "rendered": card.render(), "requested_at": time.time()}, default=str),
        encoding="utf-8")
    decision_file = DECISIONS / f"{card.incident_id}.json"
    deadline = time.time() + timeout_s
    approved = False
    while time.time() < deadline:
        if decision_file.exists():
            d = json.loads(decision_file.read_text(encoding="utf-8"))
            approved = bool(d.get("approve"))
            if audit:
                audit.append("approver", card.incident_id, who=d.get("who", "dashboard-user"))
            break
        time.sleep(poll_s)
    (PENDING / f"{card.incident_id}.json").unlink(missing_ok=True)
    decision_file.unlink(missing_ok=True)
    return approved  # timeout falls through as False
