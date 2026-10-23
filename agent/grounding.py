"""Deterministic check that every evidence reference the model cites actually appeared in the
data it was shown. Catches fabricated or corrupted trace ids / flag names / queries.
"""
from __future__ import annotations

from schema import Diagnosis, Evidence

# Evidence kinds whose `ref` must be an exact string seen in the observed data.
EXACT_KINDS = {"trace", "flag", "log", "deploy"}


def _refs(d: Diagnosis) -> list[Evidence]:
    hyps = ([d.top] if d.top else []) + d.alternatives
    return [e for h in hyps for e in h.evidence]


def ground(d: Diagnosis, observed: str, penalty: float = 0.5) -> Diagnosis:
    """Annotate grounding; demote confidence of a hypothesis with unverifiable citations."""
    bad: list[str] = []
    checked = 0
    for h in ([d.top] if d.top else []) + d.alternatives:
        h_bad = 0
        for e in h.evidence:
            if e.kind in EXACT_KINDS:
                checked += 1
                if e.ref not in observed:
                    bad.append(e.ref)
                    h_bad += 1
        if h_bad:
            h.confidence = round(h.confidence * (1 - penalty * h_bad / max(len(h.evidence), 1)), 3)
    d.ungrounded_refs = sorted(set(bad))
    d.grounding = round(1 - len(bad) / checked, 3) if checked else 1.0
    return d
