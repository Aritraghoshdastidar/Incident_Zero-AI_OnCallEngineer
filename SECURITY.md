# Security

## Design stance

Incident Zero is built so that the language model **cannot run anything**. It can only name an approved runbook and
its settings; a deterministic policy engine validates them against a fixed allowlist, and a person approves every
fix. See the "Safety model" section of the [README](README.md) and `safety/policy.py`.

Telemetry (logs, traces, error messages) is treated as **untrusted data**, because an attacker may be able to cause a
service to log hostile text. The red-team suite in `eval/redteam.py` plants such text and checks the outcome.

## Secrets

- API keys live only in a local `.env` file, which is git-ignored. Use `.env.example` as a template.
- Never paste a key into an issue, pull request or chat. If one is ever exposed, revoke it and create a new one.

## Reporting a vulnerability

Please open a private security advisory on GitHub (Security tab, "Report a vulnerability") instead of a public
issue. Include what you found, how to reproduce it, and the impact you expect. This is an independent, early-stage
project, so I can only promise a best-effort response.

## Scope and limits

This project is a demonstration at demo scale. It targets the OpenTelemetry Demo shop on a local Docker host and is
not hardened for production use. In particular, the policy engine checks that an action is *allowed*, not that it is
*wise*; the evidence on the approval slip and the person reading it cover that gap.
