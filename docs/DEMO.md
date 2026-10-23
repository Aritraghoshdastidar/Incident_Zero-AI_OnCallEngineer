# 2-minute demo script

Goal: show that the agent is **useful** (finds the real cause), **safe** (a human approves, rollback exists) and
**honest** (shows evidence and results, including failures). Record at 1080p with any screen recorder
(Windows: Win+G Game Bar, or OBS). Speak slowly; the script is about 300 words.

## Before you hit record (2 minutes of prep, not filmed)

1. Docker Desktop running; demo stack up: `docker ps` shows about 28 containers; http://127.0.0.1:8080 loads the shop.
2. Terminal A (PowerShell) in the project folder: `.\.venv\Scripts\Activate.ps1`
3. Terminal B, same folder, start the dashboard: `python -m uvicorn ui.app:app --port 8765`
   then open http://127.0.0.1:8765 in the browser (leave it on the tab).
4. **Inject the fault 3 minutes before recording** so symptoms have developed (this is the slow part, so we skip it on camera):
   `python -m tools.flagctl set paymentFailure 100%`
   (Cart-style faults are sparse and need about 4 minutes; payment is quick and dramatic. Recording the live
   shop with a failing checkout in a browser tab makes a nice opening shot.)
5. Rehearse once. Diagnosis takes 45-120 s on the free-tier model: in the video, cut that wait or say
   "about a minute" over a time-lapse. Do not pretend it is instant.

## Shot list

**0:00-0:15, the problem (shop tab, checkout failing).** Say: "It is 2 a.m., checkout is failing. On-call engineers
spend the first hour searching logs, metrics and traces. This agent does that hour, but it cannot act without
a human, and it shows its evidence."

**0:15-0:35, architecture (open `docs/architecture.html`).** Say: "Deterministic detectors build an evidence
bundle from metrics, traces and container state. The model reasons over that, every citation is verified, and its
only way to act is to pick an approved runbook. A policy engine and a human gate sit between an idea and an action."

**0:35-1:05, run it (Terminal A).**
`python -m agent.run "Customers cannot complete payment at checkout" --dashboard`
Point at the DIAGNOSIS block as it prints: root cause, confidence, evidence list, `grounding 1.0`.
Say: "Grounding 1.0 means every cited reference really exists in the data it was shown."

**1:05-1:30, approval (dashboard tab).** The decision card appears: evidence, exact command, rollback command.
Say: "Nothing runs until I approve. If nobody answers, it rejects by default." Click **Approve and run**.

**1:30-1:50, recovery (Terminal A).** It prints `status: recovered` after polling. Say: "It checks recovery over
consecutive clean readings, and would roll back to the exact previous state if it had not recovered."
Refresh the shop tab: checkout works. Then `python -m report.incident` to show the generated incident report.

**1:50-2:00, proof (open `docs/RESULTS.md`, scroll to the ablation table).** Say: "On infrastructure faults it was
never tuned on, it was 4 for 4. Against a naive LLM-plus-logs baseline it made zero wrong actions; the baseline made
three. Limitations are in the document too."

## If something goes wrong on camera

- Agent abstains: that is the feature. Say "when evidence is weak it says so instead of guessing", then re-run.
- Gemini 503: the adapter retries and falls back automatically; just wait, or cut.
- Dashboard card does not appear: confirm Terminal B is running and the agent was started with `--dashboard`.
- After recording: `python -m tools.flagctl reset` to clear any leftover fault.

## Optional second take (30 s bonus): the false alarm

With no fault injected: `python -m eval.live h_healthy --blind --no-remediate`
Shows the agent correctly taking **no action** on a healthy system, which is the other half of being trustworthy.
