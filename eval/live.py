"""Run one live fault scenario through the full agent and score it.

python -m eval.live <scenario> [--blind] [--no-remediate]
Scenarios in the `dev` group were used while building the agent. The `heldout` group are infrastructure
faults with no feature flag; they were not used to tune prompts or detectors before their first scored run.
Ground truth is the injected fault; the agent never sees this table.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Callable

from agent.executor import DecisionCard, remediate
from agent.investigator import investigate
from agent.llm import LLM
from safety import AuditLog, KillSwitch, PolicyEngine, load_runbooks
from tools import dockerctl, flagctl
from tools.config import ROOT


@dataclass
class Scenario:
    group: str
    alert: str
    service: str          # expected root-cause service ("" when nothing is wrong)
    fix_param: str        # value the correct runbook param must contain; "" means NO action is correct
    inject: Callable[[], None]
    reset: Callable[[], None]
    develop_s: int = 100

    @property
    def expect_no_action(self) -> bool:
        return not self.fix_param


def _flag(flag: str, variant: str) -> tuple[Callable, Callable]:
    return (lambda: flagctl.set_variant(flag, variant)), flagctl.reset_all


def _scn(group, alert, service, fix, injector, develop_s=100) -> Scenario:
    inject, reset = injector
    return Scenario(group, alert, service, fix, inject, reset, develop_s)


SCENARIOS: dict[str, Scenario] = {
    # --- dev group (feature-flag faults)
    "cart": _scn("dev", "Checkout error rate elevated, customers report failed orders", "cart", "cartFailure",
                 _flag("cartFailure", "100%"), develop_s=240),
    "payment": _scn("dev", "Customers cannot complete payment at checkout", "payment", "paymentFailure",
                    _flag("paymentFailure", "100%")),
    "ad_cpu": _scn("dev", "Frontend latency is high and the ad service looks overloaded", "ad", "adHighCpu",
                   _flag("adHighCpu", "on")),
    # --- held-out group (container-level faults)
    "h_redis_down": _scn("heldout", "Checkout error rate elevated, customers report failed orders", "valkey-cart",
                         "valkey-cart", (lambda: dockerctl.stop("valkey-cart"), lambda: dockerctl.start("valkey-cart")),
                         develop_s=200),
    "h_catalog_down": _scn("heldout", "Product pages are failing to load for customers", "product-catalog",
                           "product-catalog", (lambda: dockerctl.stop("product-catalog"),
                                               lambda: dockerctl.start("product-catalog")), develop_s=120),
    "h_oom": _scn("heldout", "Product recommendations are intermittently missing on the storefront", "recommendation",
                  "recommendation", (lambda: dockerctl.limit_memory("recommendation", 20),
                                     lambda: dockerctl.restore("recommendation")), develop_s=150),
    "h_cpu_throttle": _scn("heldout", "Checkout is slow, currency conversion looks sluggish", "currency", "currency",
                           (lambda: dockerctl.limit_cpu("currency", 0.02), lambda: dockerctl.restore("currency")),
                           develop_s=150),
    # --- false-alarm test: nothing is wrong, so the only correct outcome is no action
    "h_healthy": _scn("heldout", "Latency alert fired on the storefront, please investigate", "", "",
                      (lambda: None, lambda: None), develop_s=60),
    # --- coverage group: the remaining flag faults, so a hidden run on any of them is not a surprise
    "f_ad_failure": _scn("flags", "Users see errors when ads load on product pages", "ad", "adFailure",
                         _flag("adFailure", "on"), develop_s=150),
    "f_email_leak": _scn("flags", "Order confirmation email service memory keeps growing", "email", "emailMemoryLeak",
                         _flag("emailMemoryLeak", "10000x"), develop_s=240),
    "f_image_slow": _scn("flags", "Storefront product images are loading very slowly", "image-provider",
                         "imageSlowLoad", _flag("imageSlowLoad", "10sec"), develop_s=150),
    "f_kafka_lag": _scn("flags", "Order processing is delayed, the orders queue consumer lag is climbing",
                        "fraud-detection", "kafkaQueueProblems", _flag("kafkaQueueProblems", "5sec"), develop_s=180),
    "f_kafka_dead": _scn("flags", "Orders are being produced but nothing is consuming them", "fraud-detection",
                         "kafkaConsumerDead", _flag("kafkaConsumerDead", "on"), develop_s=240),
    "f_payment_down": _scn("flags", "Payment service appears to be unreachable from checkout", "payment",
                           "paymentUnreachable", _flag("paymentUnreachable", "on"), develop_s=150),
    "f_catalog_lock": _scn("flags", "Product catalog responses are slow, database looks contended", "product-catalog",
                           "productCatalogLockContention", _flag("productCatalogLockContention", "on"), develop_s=150),
    "f_reco_cache": _scn("flags", "Recommendation requests are failing intermittently", "recommendation",
                         "recommendationCacheFailure", _flag("recommendationCacheFailure", "on"), develop_s=150),
    "f_shipping_slow": _scn("flags", "International shipping quotes are very slow at checkout", "shipping",
                            "intlShippingSlowdown", _flag("intlShippingSlowdown", "10sec"), develop_s=150),
    "f_flood": _scn("flags", "Frontend is overwhelmed by a flood of homepage requests", "load-generator",
                    "loadGeneratorFloodHomepage", _flag("loadGeneratorFloodHomepage", "on"), develop_s=120),
}


def run(name: str, blind: bool, remediate_it: bool) -> dict:
    sc = SCENARIOS[name]
    sc.reset()
    flagctl.reset_all()
    sc.inject()
    since_ts = time.time()
    print(f"[{name}] injected; letting it develop {sc.develop_s}s", flush=True)
    time.sleep(sc.develop_s)

    audit = AuditLog(ROOT / "data" / "audit" / "eval.jsonl")
    engine = PolicyEngine(load_runbooks(ROOT / "runbooks"), KillSwitch(ROOT / ".killswitch"))
    llm = LLM()
    t0 = time.time()
    try:
        diag = investigate(sc.alert, llm, audit, blind=blind, since_ts=since_ts)
    except Exception:
        sc.reset()  # never leave an injected fault behind if the agent itself fails
        raise
    t_diag = time.time() - t0

    action = diag.proposed_action
    result = {"scenario": name, "group": sc.group, "blind": blind, "abstained": diag.abstain,
              "service_correct": (diag.top is None or diag.abstain) if sc.expect_no_action
              else bool(diag.top) and diag.top.service == sc.service,
              "action_correct": (action is None) if sc.expect_no_action
              else bool(action) and sc.fix_param in map(str, action.params.values()),
              "proposed": f"{action.runbook_id} {action.params}" if action else None,
              "confidence": diag.top.confidence if diag.top else None, "grounding": diag.grounding,
              "root_cause": diag.top.root_cause if diag.top else None,
              "diagnose_s": round(t_diag, 1), "tokens": llm.usage.prompt_tokens + llm.usage.completion_tokens}
    if remediate_it:
        def approver(card: DecisionCard) -> bool:
            audit.append("approver", card.incident_id, who="auto(test)")
            return True
        result["remediation"] = remediate(diag, engine, audit, approver, timeout_s=360)["status"]
    sc.reset()
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # model text may contain non-cp1252 characters on Windows
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=SCENARIOS)
    ap.add_argument("--blind", action="store_true")
    ap.add_argument("--no-remediate", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.scenario, a.blind, not a.no_remediate), indent=1))
    print("flags left active:", flagctl.active())
