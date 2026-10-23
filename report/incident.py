"""Generate a human-readable incident report from the hash-chained audit log.

python -m report.incident [incident_id] [--audit path]    (default: most recent incident)
The report is derived only from audited events, so it cannot claim anything the agent did not record.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _t(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(ts)) + "Z"


def build(events: list[dict], incident_id: str) -> str:
    ev = [e for e in events if e["incident_id"] == incident_id]
    if not ev:
        raise SystemExit(f"no events for {incident_id}")
    by: dict[str, list[dict]] = {}
    for e in ev:
        by.setdefault(e["event"], []).append(e)
    diag = by.get("diagnosis", [{}])[-1].get("data", {})
    card = by.get("decision_card", [{}])[-1].get("data", {}).get("card", {})
    verified = by.get("verified", [{}])[-1].get("data", {})
    status = ("RECOVERED" if verified.get("recovered") else
              "ROLLED BACK" if "rolled_back" in by else
              "ESCALATED (fix applied, recovery not confirmed: needs human review)" if "escalated" in by else
              "REJECTED" if "rejected" in by else
              "NO ACTION" if "no_action" in by else "IN PROGRESS / NOT VERIFIED")
    tools = [e["data"].get("tool", "?") for e in by.get("tool_call", [])]
    out = [
        f"# Incident report {incident_id}",
        f"**Status:** {status}  |  **Opened:** {_t(ev[0]['ts'])}  |  **Duration:** {ev[-1]['ts'] - ev[0]['ts']:.0f}s",
        "",
        "## Diagnosis",
        f"- Root cause: {diag.get('root_cause') or '(abstained)'}",
        f"- Confidence: {diag.get('confidence')}   Evidence grounding: {diag.get('grounding')}",
        f"- Ungrounded references flagged: {diag.get('ungrounded') or 'none'}",
        f"- Abstained: {diag.get('abstain')}",
        "",
        "## Investigation steps",
        f"- Evidence bundle built: {'yes' if 'bundle_built' in by else 'no'}",
        f"- Drill-down tool calls: {', '.join(tools) if tools else 'none'}",
        "",
        "## Action",
    ]
    if card:
        out += [f"- Proposed: `{card.get('runbook_id')}` {card.get('params')}  (risk: {card.get('risk')})",
                f"- Command: `{' '.join(card.get('command', []))}`",
                f"- Rollback: `{' '.join(card['rollback_command'])}`" if card.get("rollback_command") else "- Rollback: none"]
        who = by.get("approver", [{}])[-1].get("data", {}).get("who", "human" if "approved" in by else "n/a")
        out.append(f"- Approval: {'approved by ' + who if 'approved' in by else 'not approved'}")
    else:
        out.append(f"- No action taken: {by.get('no_action', [{}])[-1].get('data', {}).get('reason', 'n/a')}")
    if verified:
        out += ["", "## Verification",
                f"- Recovered: {verified.get('recovered')}",
                f"- Residual errors: {len(verified.get('residual_errors', []))}",
                f"- Entrypoint anomalies: {len(verified.get('entrypoint_anomalies', []))}"]
    out += ["", "## Audit timeline"]
    out += [f"- {_t(e['ts'])}  {e['event']}" for e in ev]
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("incident_id", nargs="?")
    ap.add_argument("--audit", default=str(ROOT / "data" / "audit" / "audit.jsonl"))
    a = ap.parse_args()
    events = _load(Path(a.audit))
    print(build(events, a.incident_id or events[-1]["incident_id"]))
