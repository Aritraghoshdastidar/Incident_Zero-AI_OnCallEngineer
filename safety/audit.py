"""Append-only, hash-chained audit log: tampering with any line breaks the chain."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last = self._tail_hash()

    def _tail_hash(self) -> str:
        if not self._path.exists():
            return "0" * 64
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1])["hash"] if lines else "0" * 64

    def append(self, event: str, incident_id: str, **data) -> dict:
        record = {"ts": time.time(), "incident_id": incident_id, "event": event, "data": data, "prev": self._last}
        record["hash"] = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        self._last = record["hash"]
        return record

    def verify(self) -> bool:
        prev = "0" * 64
        for line in self._path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            claimed = rec.pop("hash")
            if rec["prev"] != prev:
                return False
            if hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest() != claimed:
                return False
            prev = claimed
        return True
