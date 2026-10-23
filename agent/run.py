"""CLI: python -m agent.run "<alert text>" [--auto-approve]

--auto-approve exists only for scripted tests of our own harness and is recorded in the audit log
as approver=auto(test). In real use the approver is a human (CLI prompt here, dashboard later).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from safety import AuditLog, KillSwitch, PolicyEngine, load_runbooks
from tools.config import ROOT

from .executor import DecisionCard, remediate
from .investigator import investigate
from .llm import LLM


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("alert")
    ap.add_argument("--auto-approve", action="store_true")
    ap.add_argument("--dashboard", action="store_true", help="wait for approval in the web dashboard (ui.app)")
    ap.add_argument("--json-out", help="write the diagnosis and remediation result as JSON (for automated scoring)")
    ap.add_argument("--blind", action="store_true", help="do not read feature-flag state (infra-only evidence)")
    ap.add_argument("--since", type=float, help="alert start time (unix seconds); defaults to 5 minutes ago")
    ap.add_argument("--timeout", type=int, default=300, help="max seconds to wait for verified recovery")
    args = ap.parse_args()

    audit = AuditLog(ROOT / "data" / "audit" / "audit.jsonl")
    engine = PolicyEngine(load_runbooks(ROOT / "runbooks"), KillSwitch(ROOT / ".killswitch"))
    llm = LLM()

    diag = investigate(args.alert, llm, audit, blind=args.blind, since_ts=args.since)
    print("\n=== DIAGNOSIS ===")
    print(diag.model_dump_json(indent=1, exclude={"alternatives"}))

    def approver(card: DecisionCard) -> bool:
        print("\n=== DECISION CARD ===\n" + card.render())
        if args.auto_approve:
            audit.append("approver", card.incident_id, who="auto(test)")
            return True
        if args.dashboard:
            from ui.approver import file_approver
            print("Waiting for approval in the dashboard (http://127.0.0.1:8765) ...", flush=True)
            return file_approver(card, audit=audit)
        return input("\nApprove? [y/N] ").strip().lower() == "y"

    result = remediate(diag, engine, audit, approver, args.timeout)
    print("\n=== RESULT ===\n" + json.dumps(result, indent=1, default=str))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(
            {"diagnosis": diag.model_dump(), "remediation": result, "audit_chain_intact": audit.verify()},
            indent=1, default=str), encoding="utf-8")
    print(f"\naudit chain intact: {audit.verify()}   llm: {llm.usage}")


if __name__ == "__main__":
    main()
