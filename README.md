<h1 align="center">Incident Zero</h1>

<p align="center"><b>An AI on-call engineer you can trust.</b><br>
It reads telemetry, names the root cause with checkable evidence, proposes a fix from an approved list, waits for a person to approve it, and verifies that the system really recovered.</p>

<p align="center">
  <a href="https://github.com/Aritraghoshdastidar/Incident_Zero-AI_OnCallEngineer/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Aritraghoshdastidar/Incident_Zero-AI_OnCallEngineer/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-2459b0">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-237a57">
  <img alt="Tests: 32 passing" src="https://img.shields.io/badge/tests-32%20passing-237a57">
  <a href="https://aritraghoshdastidar.github.io/Incident_Zero-AI_OnCallEngineer/"><img alt="Live demo" src="https://img.shields.io/badge/live%20demo-open-101b2d"></a>
</p>

<p align="center">
  <a href="https://aritraghoshdastidar.github.io/Incident_Zero-AI_OnCallEngineer/"><b>Live demo</b></a> &nbsp;|&nbsp;
  <a href="docs/RESULTS.md">Results and method</a> &nbsp;|&nbsp;
  <a href="docs/architecture.html">Architecture</a> &nbsp;|&nbsp;
  <a href="#quickstart">Quickstart</a>
</p>

<p align="center">
  <a href="https://aritraghoshdastidar.github.io/Incident_Zero-AI_OnCallEngineer/"><img src="docs/images/hero.gif" alt="Replay of a payment failure: the agent gathers evidence, asks for approval, runs the fix and verifies recovery, on the real recorded metrics" width="760"></a>
</p>
<p align="center"><sub>A real recorded incident on its real metrics. The replay pauses at the approval slip: in the live demo, you decide.</sub></p>

## What it is

When something breaks in a running system, an on-call engineer spends the first hour searching logs, metrics and
traces for a cause. Incident Zero does that first hour. It is built for the
[OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) shop (about 28 containers on one laptop)
and was developed in response to the "Incident Zero: Build an AI On-Call Engineer" hackathon brief.

It is designed around three claims, each backed by a test you can run:

- **Useful.** It found the cause of failures it was never tuned on: 4 of 4 infrastructure faults with no feature flag, each fixed and verified.
- **Safe.** The language model cannot run anything. It can only name an approved runbook, a deterministic policy engine checks it, and a person approves every fix.
- **Honest.** It cites evidence that is verified against what it was shown, says "I am not sure" when it is not, and the results below include the misses.

## See it in action

<table>
  <tr>
    <td width="50%"><img src="docs/images/site-slip.png" alt="The approval slip showing evidence, the exact command and its undo"><br><sub><b>The approval slip.</b> Evidence, confidence, the exact command that will run and the exact command that undoes it.</sub></td>
    <td width="50%"><img src="docs/images/site-replay.png" alt="A finished replay of a container that ran out of memory: memory drops to zero and returns after the approved fix"><br><sub><b>Real traces.</b> A container killed for running out of memory, then restored after approval. Red and blue are two measurements, each on its own scale.</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/site-trick.png" alt="The policy playground blocking a shell command hidden in a setting"><br><sub><b>Try to trick it.</b> Send a hostile proposal to a copy of the real policy rules and see why it is blocked.</sub></td>
    <td><img src="docs/images/site-scorecard.png" alt="Scorecard comparing a plain LLM with this agent across seven failures"><br><sub><b>Scorecard.</b> The same seven failures, a plain LLM reading raw logs against this agent, with misses shown.</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/dashboard.png" alt="The operator dashboard with a pending approval card"><br><sub><b>Operator dashboard.</b> Pending approvals, the incident timeline and a kill switch.</sub></td>
    <td><img src="docs/images/site-dark.png" alt="The demo site in dark mode"><br><sub><b>Dark mode</b> and a phone layout (the chart scrolls like a paper roll) are built in.</sub></td>
  </tr>
</table>

## How it works

```mermaid
flowchart LR
    A[Alert + start time] --> B[Signal detectors]
    subgraph Eyes[Read-only tools: untrusted data]
      P[(Prometheus)] --- B
      J[(Jaeger traces)] --- B
      L[(Container logs)] --- B
      D[Container state] --- B
    end
    B --> E[Evidence bundle<br/>novelty-tagged]
    E --> M[LLM investigator<br/>up to 4 drill-downs]
    M --> G[Grounding check<br/>verify every citation]
    G --> Dx[Diagnosis<br/>confidence, evidence, abstain]
    Dx --> PE{Policy engine<br/>allowlist + typed settings}
    PE -- rejected --> X[No action]
    PE -- allowed --> C[Decision card]
    C --> H{Human approval}
    H -- reject or timeout --> X
    H -- approve --> R[Dry run, then execute]
    R --> V[Verify recovery<br/>poll, traffic-aware]
    V -- recovered --> Rep[Incident report]
    V -- got worse --> RB[Roll back to the exact prior state] --> Rep
    V -- cannot confirm --> ES[Leave the fix, escalate to a person] --> Rep
    KS[Kill switch] -.-> PE
    AU[(Hash-chained audit log)] -.-> Dx
    AU -.-> R
    AU -.-> V
```

| Stage | What happens |
|---|---|
| **1. Evidence** (plain code, no AI) | Metric anomalies against each service's own baseline; error signatures from traces, tagged *new* or *already there*; CPU, memory and Kafka-lag changes; container state (stopped, killed, limited); optionally feature-flag state. |
| **2. Investigation** | The model reasons over that compact bundle, may make up to four drill-down calls, and returns a structured diagnosis. All telemetry is marked as untrusted data. |
| **3. Grounding** | Every trace id, flag and log reference the model cites must appear in the data it was shown. Fabricated or corrupted citations are flagged and confidence is cut. |
| **4. Policy** | The only way to act is a runbook name plus settings. A deterministic engine checks the allowlist, exact settings, exact types and approved values. |
| **5. Approval** | A decision card shows the evidence, the exact command and its undo. A person approves in the terminal or the dashboard. No answer means reject. |
| **6. Fix and verify** | Snapshot, dry run, execute, then poll until consecutive clean readings with traffic still flowing. |
| **7. Outcome** | Recovered. Or rolled back to the exact previous value if things got *worse*. Or left in place and escalated if recovery cannot be confirmed, because reverting would put the original fault back. |
| **8. Audit** | A hash-chained log records every step; the incident report is built only from it. |

## Safety model

| Layer | What it stops |
|---|---|
| Untrusted-data marking | Hostile instructions in a log line being treated as commands |
| Model discipline | The model obeying planted text (7 of 7 attacks resisted in the red-team run) |
| Grounding check | Invented or corrupted evidence |
| Policy engine | Any action off the allowlist, with wrong settings, types or values (fuzz-tested) |
| Human approval | Anything running without a person seeing the evidence; fails closed on timeout |
| Kill switch | Everything, from any process |
| Dry run and exact-undo rollback | Blind execution and a fix that makes things worse |
| Escalate, not revert | A correct fix being undone because recovery was hard to measure |
| Hash-chained audit log | Quiet tampering with the record |

> **A limit worth stating.** The policy engine checks that an action is *allowed*, not that it is *wise*. A restart of
> the frontend is a legal action even when it is the wrong fix. That case is covered by the evidence on the approval
> slip and the person reading it, not by the policy engine.

## Results

All numbers come from recorded runs on one laptop with a free-tier Gemini model. **The samples are small** (single
runs, one fault each), so treat them as indicative. Method, labels and the full failure list are in
[`docs/RESULTS.md`](docs/RESULTS.md).

| Test | Result |
|---|---|
| Held-out infrastructure faults (stopped Redis, stopped catalog, out-of-memory loop, CPU throttle), full loop, never tuned against | **4 of 4** correct and recovered |
| Paired comparison against a naive "LLM + raw logs" baseline, 7 scenarios | This agent: **6 of 7 correct, 0 wrong actions**. Baseline: 4 of 7 correct, **3 wrong actions**, each stated at 90% confidence or more |
| Prompt-injection red team (7 attacks planted in telemetry) | **7 of 7 resisted**, no leakage |
| False alarm on a healthy system | Correct: took no action |
| Automated tests | **32 passing**, including random-input fuzzing of the policy engine |

Honest notes: the agent is about twice as slow as the baseline (80 to 290 seconds per diagnosis on a free tier);
it took no action on one scenario the baseline got right; results re-run after seeing failures are labelled as
*development* numbers; and the model partly remembers this demo's flag names, so the container-level faults are the
cleanest evidence. A real bug found by rehearsing the demo (a false rollback) and its fix are written up in the
results document.

## Quickstart

**Prerequisites:** Docker Desktop, Python 3.11 or newer, and a free [Gemini API key](https://aistudio.google.com/apikey).

```bash
# 1. Start the shop with its monitoring stack
git clone https://github.com/open-telemetry/opentelemetry-demo otel-demo
(cd otel-demo && docker compose -f compose.yaml -f compose.full.yaml \
    -f compose.observability.yaml -f compose.extras.yaml up -d)

# 2. Install the agent
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                 # then put your key in .env

# 3. Check it (offline; no Docker or key needed)
python -m pytest
```

**Run your first incident.** Break something, start the approval dashboard, and let the agent handle it:

```bash
python -m tools.flagctl set paymentFailure 100%            # inject a failure
python -m uvicorn ui.app:app --port 8765                   # approvals appear at http://127.0.0.1:8765
# wait about 3 minutes for symptoms to develop, then in a second terminal:
python -m agent.run "Customers cannot complete payment at checkout" --dashboard
python -m report.incident                                  # the incident report
python -m tools.flagctl reset                              # put everything back
```

Windows tip: use `127.0.0.1`, not `localhost`. On Windows `localhost` resolves to IPv6 first and Docker's proxy drops it.

## Usage

| Command | What it does |
|---|---|
| `python -m agent.run "<alert>" [--dashboard] [--blind] [--json-out file]` | Diagnose, ask for approval, fix, verify. `--blind` hides feature-flag state. |
| `python -m eval.live <scenario> [--blind]` | Inject one of 18 faults, run the whole loop, score it. |
| `python -m eval.batch <tag> <scenarios>` | Unattended batch that waits for a quiet system between faults. |
| `python -m eval.ablation` | Paired comparison against the naive baseline. |
| `python -m eval.redteam` | Prompt-injection suite (offline). |
| `python -m report.incident` | Incident report from the audit log. |
| `python site/build_data.py` | Rebuild the demo website's data from the recorded runs. |
| `make test`, `make lint`, `make dashboard` | Shortcuts. |

## Project layout

```
agent/      detectors (signals), investigation loop, grounding check, executor, LLM adapter
tools/      read-only telemetry; feature-flag and container fault injection with exact restore
runbooks/   the four approved actions as YAML: settings, risk, dry run, rollback
safety/     policy engine, kill switch, hash-chained audit log
schema/     the typed Diagnosis contract (evidence required unless abstaining)
eval/       scenario runner, batch runner, baseline comparison, red team
ui/         operator dashboard (FastAPI) with file-based approvals
report/     incident report generated from audited events
site/       interactive demo website (static; replays recorded runs)
docs/       results, architecture sketch, demo script, images
tests/      32 offline tests
```

## Engineering notes

Things that bit us, kept here because they cost real time:

- Jaeger 2 only serves the v3 API (OTLP-JSON, newline-delimited).
- The load generator keeps one trace open for a whole user session. A time-window query returns the whole trace, so error spans must be filtered by their own start time or stale errors leak in.
- A one-minute `rate()` over span metrics is empty at this export interval; use two minutes or more.
- Faults on low-traffic paths (cart `EmptyCart`, about two errors per five minutes) need an evidence window of at least five minutes.
- Services cache feature flags, so a fix takes two to three minutes to show. Verification must poll, not sleep.
- Frontend p95 latency on a laptop swings between about 60 ms and 4.4 s on its own, so a fixed latency ratio is not evidence of failure.
- `docker update --cpus 0` does not remove a CPU limit; set it to the host CPU count.
- Free-tier models return 503s and retire without notice: the adapter retries, rotates keys and skips retired models.

## Limitations and roadmap

- **Speed:** 80 to 290 seconds per diagnosis on a free-tier model.
- **Scale of evidence:** single runs, one application, one model family.
- **Scope:** demo scale. Runbooks target Docker, not Kubernetes, and it is not hardened for production.
- **Ambiguity:** some faults look like networking problems from telemetry alone; the agent abstains instead of guessing.
- **Next:** open a ticket with the evidence on detection (Jira or GitHub Issues) and let a second agent prepare a patch for human review; look up similar past incidents; tiered autonomy for low-risk fixes; more applications and models.

## Contributing, security and license

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). To report a vulnerability, see
[SECURITY.md](SECURITY.md). Released under the [MIT License](LICENSE).

## Acknowledgements and disclaimer

Runs against the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) (Apache-2.0), which is not
redistributed here. This is an independent project built in response to a hackathon brief; it is not affiliated with
or endorsed by Bosch or PES University. It was built with AI assistance (Claude Code), with design
decisions, evaluation and review by the author.
