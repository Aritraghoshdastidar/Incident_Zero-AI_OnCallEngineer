# Results

All numbers come from live runs against the OpenTelemetry Demo on one laptop, with a free-tier Gemini model
(`gemini-2.5-flash`, low reasoning effort). Raw rows are in `data/results/*.jsonl`. Samples are small (single runs,
one fault instance per scenario), so treat every figure as indicative, not statistical.

**Scoring:** an outcome is *correct* when the proposed runbook parameter names the injected fault (or, for the
healthy-system test, when no action is proposed). A *wrong action* is any proposed action that is not the correct one.
*Blind* means feature-flag / config state is hidden from the agent, forcing it to reason from telemetry and
container state alone. *Visible* mode exposes flag state, as an on-call engineer could read it from the flag service.

## 1. Held-out infrastructure faults (no feature flag, never used to tune prompts or detectors)

Full loop: diagnose, human-gated fix (test auto-approve, logged as `auto(test)`), verified recovery.

| Fault | Diagnosis | Confidence | Outcome |
|---|---|---|---|
| Redis (`valkey-cart`) stopped; same error text as the `cartFailure` flag | correct | 0.95 | recovered |
| `product-catalog` stopped | correct | 0.99 | recovered |
| `recommendation` OOM-kill loop (20 MB limit) | correct | 0.95 | recovered |
| `currency` CPU-throttled (0.02 CPU) | correct | 0.95 | recovered |

4 of 4 correct and recovered, 0 wrong actions. Note: the OOM scenario's first attempt crashed on a provider API error
(a Gemini thought-signature requirement) before the agent reasoned; it was re-run after an adapter-only fix.
The other three are first-run results.

## 2. Paired ablation: hybrid agent vs naive "LLM + raw logs" baseline (7 scenarios, same injected fault each)

| | Correct | Abstained | Wrong actions | Avg time | Avg tokens |
|---|---|---|---|---|---|
| Hybrid agent (this project) | 6/7 | 1 | **0** | 119 s | 8.6k |
| Naive baseline (raw logs from every container, one call) | 4/7 | 0 | **3** | 56 s | 30.2k |

The baseline's three wrong actions (cart, OOM, CPU throttle) were all stated at 0.90-0.95 confidence. The failures are
the ones whose evidence is not in the logs (container state, resource limits) or is buried in noise. On easy cases
(payment, catalog down) the baseline matched the hybrid. The hybrid is about 2x slower (several LLM calls) and abstained
once (`ad_cpu`) where the baseline was right. n=7: indicative only.

## 3. Prompt-injection red team (hostile text planted inside telemetry)

Seven attacks: instruction override, fake `</telemetry_data>` tag, non-allowlisted runbook, shell injection in a
parameter, secret exfiltration, fabricated evidence, role confusion.

Model resisted 7/7; 0 severe failures; no secret leakage. Caveat: the model was never fooled, so the policy layer was
not exercised by this suite. It is covered separately: the policy engine rejects anything off the allowlist or outside
a closed parameter set (property-based fuzzing, 100s of generated inputs), and every runbook requires approval.

## 4. Hidden-test simulation (unattended; blind; diagnosis only), first run before fixes

| Scenario | Result | Note |
|---|---|---|
| healthy system (false alarm) | correct: no action | took 289 s |
| adFailure | correct action | grounding 0.0: the model named a flag it was never shown (likely pretraining knowledge of the demo); confidence was demoted by the grounding check |
| Kafka consumer lag | missed (abstained) | no detector for queue growth |
| paymentUnreachable | missed (abstained at 0.9, contradictory) | inherently ambiguous without flag state |
| recommendationCacheFailure | correct action | confidence 0.64, grounding 0.5 |
| intlShippingSlowdown | correct action | 0.95 |
| loadGeneratorFloodHomepage | right action, wrong service | blamed a leftover restart count from the earlier OOM test |

5 of 7 correct, 3 abstentions, 0 wrong actions.

## 5. What changed after seeing those failures (fixes at the detector/prompt layer, not per scenario)

1. Added a baseline-relative resource detector (CPU/memory saturation, Kafka lag growth, lost consumer-group members).
   Standing high lag on a healthy consumer is not flagged; the detector is quiet on a healthy system (checked live).
2. Restart counts only count inside the incident window (fixes the leftover-restart leak).
3. Prompt rule: abstain only below 0.6 confidence, never at high confidence.

Two further changes came from the re-run itself (see section 6): reverting a prompt rule that caused a wrong action,
and requiring live consumers before reporting Kafka lag growth. Between scenarios the batch runner now waits for the
system to be quiet instead of using a fixed cooldown, because services cache flag values for 2-3 minutes and one
scenario's leftover errors had leaked into the next.

## 6. Post-fix re-runs (DEVELOPMENT numbers: these scenarios were re-run after their failures were seen)

These are not clean held-out results. The clean held-out result is section 1.

Blind mode (flag state hidden):

| Scenario | Outcome | Confidence | Notes |
|---|---|---|---|
| paymentUnreachable | correct | 0.95 | read the `badAddress` DNS failure in checkout |
| Kafka consumer lag | correct | 1.0 (grounding 1.0) | final run; an earlier run in this series proposed `restart_service payment` at 0.85 (a wrong action) after a prompt rule I added encouraged guessing. Reverted. |
| loadGeneratorFlood | correct | 0.71 | grounding 0.0: flag named from model memory, demoted by the check |
| adHighCpu | correct | 0.475 | grounding 0.0, low confidence |
| healthy system (false alarm) | correct: no action | 0.5 | an intermediate run flagged standing `accounting` lag; fixed |

Flag-visible mode (config state readable):

| Scenario | Outcome | Confidence |
|---|---|---|
| paymentUnreachable | correct | 1.0, grounding 1.0 |
| adFailure | correct | 1.0, grounding 1.0 |

Observed wrong actions across the whole project: 3 by the naive baseline (ablation), 1 by the hybrid agent
(the prompt-induced kafka case above, found and fixed during development). 0 in the clean held-out run.

## 7. Found while rehearsing the demo: a false rollback (fixed)

Rehearsing the dashboard approval flow exposed a real flaw. The diagnosis and fix were correct, but verification
reported "not recovered" and rolled the fix back, which switched the original fault back on. Cause: recovery checked
entry-point latency against a 2x baseline ratio, but frontend p95 on this laptop swings between about 60 ms and
4.4 s on its own, so the check was noise. Two design changes followed:

1. Recovery now judges entry-point error rate, and judges latency only on the diagnosed service, against its own
   pre-fix reading, and only if that service had a latency problem before the fix.
2. Rollback happens only if things got worse (new errors the fix did not start with). If recovery simply cannot be
   confirmed, the fix stays in place and the incident is escalated to a person, because reverting would put the
   original fault back.

A re-run of the same rehearsal then ended `recovered`. The incidents recorded earlier (sections 1 to 4 and the demo
site) used the previous verifier, which was stricter on latency but gave the false rollback above in that one case.
Tests: 32 passing, including the exact frontend-latency false positive.

## Where it fails and why (known limitations)

- **Slow:** 80-290 s per diagnosis, dominated by LLM latency (several calls on a free tier).
- **Sparse faults need long windows:** a fault on a low-traffic path (cart `EmptyCart`, about 2 errors per 5 minutes)
  leaves no samples in short windows, so evidence collection needs at least 5 minutes of data.
- **Pretraining leakage:** the model appears to know the demo's feature-flag names, which can make blind mode look
  better than it is. The grounding check catches uncited flag claims; the held-out container faults are the clean test.
- **Ambiguity without config access:** some faults (`paymentUnreachable`) look like a networking problem from
  telemetry alone. The agent abstains instead of guessing; with flag state visible it can name the cause.
- **Scale of evidence:** small samples, one fault instance per scenario, one LLM family, one application.
- **Cost realism:** the free-tier LLM can return 503s and retire models; the adapter retries, rotates keys and
  falls back, but latency varies with provider load.
