from agent.grounding import ground
from schema import Diagnosis, Evidence, Hypothesis


def diag(ref: str, kind: str = "trace") -> Diagnosis:
    h = Hypothesis(root_cause="x", service="cart", confidence=0.8,
                   evidence=[Evidence(kind=kind, ref=ref, summary="s")])
    return Diagnosis(incident_id="i", summary="s", top=h)


def test_exact_reference_is_grounded():
    d = ground(diag("044da9fc3835f3699247a8d5f37efac4"), "trace 044da9fc3835f3699247a8d5f37efac4 failed")
    assert d.grounding == 1.0 and not d.ungrounded_refs


def test_corrupted_trace_id_is_flagged_and_confidence_demoted():
    d = ground(diag("044da9fc3835f3699247a8d5f377efac4"), "trace 044da9fc3835f3699247a8d5f37efac4 failed")
    assert d.grounding == 0.0 and d.ungrounded_refs
    assert d.top.confidence < 0.8


def test_metric_refs_are_not_exact_checked():
    d = ground(diag("rate(x[2m])", kind="metric"), "nothing relevant")
    assert d.grounding == 1.0
