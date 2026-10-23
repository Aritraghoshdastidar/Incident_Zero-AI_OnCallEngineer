"""Controlled access to the demo's fault-injection flags (flagd reads this file live).

Used two ways: by the eval harness to inject faults, and by the `disable_flag`
runbook as the remediation. A pristine baseline copy is kept for rollback.
"""
from __future__ import annotations

import json
import shutil
import sys

from .config import FLAGS_BASELINE, FLAGS_FILE

PREV_FILE = FLAGS_BASELINE.with_name("flags.prev.json")


def _load() -> dict:
    return json.loads(FLAGS_FILE.read_text(encoding="utf-8"))


def _save(doc: dict) -> None:
    FLAGS_FILE.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def snapshot_baseline() -> None:
    if not FLAGS_BASELINE.exists():
        FLAGS_BASELINE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FLAGS_FILE, FLAGS_BASELINE)


def get(flag: str) -> str:
    return _load()["flags"][flag]["defaultVariant"]


def show(flag: str) -> dict:
    f = _load()["flags"][flag]
    return {"flag": flag, "current": f["defaultVariant"], "variants": list(f["variants"]), "description": f["description"]}


def active() -> dict[str, str]:
    """Every flag currently not on its 'off' variant."""
    return {n: f["defaultVariant"] for n, f in _load()["flags"].items() if f["defaultVariant"] != "off"}


def _prev() -> dict:
    return json.loads(PREV_FILE.read_text(encoding="utf-8")) if PREV_FILE.exists() else {}


def set_variant(flag: str, variant: str) -> None:
    snapshot_baseline()
    doc = _load()
    if variant not in doc["flags"][flag]["variants"]:
        raise ValueError(f"{flag} has no variant {variant!r}")
    prev = _prev()
    prev[flag] = doc["flags"][flag]["defaultVariant"]  # exact pre-change value, for a true undo
    PREV_FILE.write_text(json.dumps(prev), encoding="utf-8")
    doc["flags"][flag]["defaultVariant"] = variant
    _save(doc)


def undo(flag: str) -> None:
    """Restore the value the flag had immediately before the last set_variant()."""
    prev = _prev()
    if flag not in prev:
        raise ValueError(f"no recorded previous value for {flag}")
    doc = _load()
    doc["flags"][flag]["defaultVariant"] = prev[flag]
    _save(doc)


def restore(flag: str) -> None:
    base = json.loads(FLAGS_BASELINE.read_text(encoding="utf-8"))
    doc = _load()
    doc["flags"][flag]["defaultVariant"] = base["flags"][flag]["defaultVariant"]
    _save(doc)


def reset_all() -> None:
    if FLAGS_BASELINE.exists():
        shutil.copyfile(FLAGS_BASELINE, FLAGS_FILE)


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "set":
        set_variant(args[0], args[1])
    elif cmd == "restore":
        restore(args[0])
    elif cmd == "undo":
        undo(args[0])
    elif cmd == "show":
        print(json.dumps(show(args[0])))
    elif cmd == "active":
        print(json.dumps(active()))
    elif cmd == "reset":
        reset_all()
    else:
        sys.exit(f"unknown command {cmd}")
