"""Operator dashboard: live incident timeline, pending approvals, kill switch.

uvicorn ui.app:app --port 8765
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from safety import KillSwitch
from tools.config import ROOT

from .approver import DECISIONS, PENDING

AUDIT_FILES = [ROOT / "data" / "audit" / "audit.jsonl", ROOT / "data" / "audit" / "eval.jsonl"]
app = FastAPI(title="Incident Zero")
kill = KillSwitch(ROOT / ".killswitch")


def _events() -> list[dict]:
    rows: list[dict] = []
    for f in AUDIT_FILES:
        if f.exists():
            rows += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return sorted(rows, key=lambda r: r["ts"])


class Decision(BaseModel):
    approve: bool


class Kill(BaseModel):
    engage: bool


@app.get("/api/incidents")
def incidents() -> list[dict]:
    by: dict[str, list[dict]] = {}
    for e in _events():
        by.setdefault(e["incident_id"], []).append(e)
    out = []
    for iid, ev in by.items():
        names = {e["event"] for e in ev}
        diag = next((e["data"] for e in reversed(ev) if e["event"] == "diagnosis"), {})
        ver = next((e["data"] for e in reversed(ev) if e["event"] == "verified"), None)
        status = ("recovered" if ver and ver.get("recovered") else "rolled_back" if "rolled_back" in names
                  else "needs_review" if "escalated" in names
                  else "rejected" if "rejected" in names else "awaiting_approval" if (PENDING / f"{iid}.json").exists()
                  else "no_action" if "no_action" in names
                  else "diagnosed" if "diagnosis" in names and "decision_card" not in names else "in_progress")
        out.append({"incident_id": iid, "status": status, "opened": ev[0]["ts"], "root_cause": diag.get("root_cause"),
                    "confidence": diag.get("confidence"), "grounding": diag.get("grounding"),
                    "events": [{"ts": e["ts"], "event": e["event"]} for e in ev]})
    return sorted(out, key=lambda i: -i["opened"])[:25]


@app.get("/api/pending")
def pending() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PENDING.glob("*.json"))] if PENDING.exists() else []


@app.post("/api/decision/{incident_id}")
def decide(incident_id: str, body: Decision) -> dict:
    if not incident_id.replace("-", "").isalnum():  # incident ids become filenames: never trust the path
        raise HTTPException(400, "bad incident id")
    if not (PENDING / f"{incident_id}.json").exists():
        raise HTTPException(404, "no pending approval for that incident")
    DECISIONS.mkdir(parents=True, exist_ok=True)
    (DECISIONS / f"{incident_id}.json").write_text(
        json.dumps({"approve": body.approve, "who": "dashboard-user", "at": time.time()}), encoding="utf-8")
    return {"ok": True}


@app.get("/api/killswitch")
def get_kill() -> dict:
    return {"engaged": kill.engaged()}


@app.post("/api/killswitch")
def set_kill(body: Kill) -> dict:
    kill.engage() if body.engage else kill.release()
    return {"engaged": kill.engaged()}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
