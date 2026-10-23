# Contributing

Thanks for taking a look. Issues and pull requests are welcome.

## Set up

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest                   # offline: no Docker, no API key needed
ruff check .
```

The tests are fully offline. Running the agent against a live system also needs Docker and the OpenTelemetry Demo
(see the README quickstart) plus a free Gemini API key in `.env`.

## Ground rules

- **Safety first.** The model must never gain a way to run arbitrary commands. New actions are added as YAML runbooks
  in `runbooks/`, with a closed set of allowed values for every setting, a dry run where possible, and an undo.
  Every runbook needs a policy test.
- **Evidence over eloquence.** A new detector should compare against a baseline and not a fixed threshold, and should
  come with a test that shows it stays quiet on a healthy system.
- **Honest results.** If you change a prompt or detector after seeing a failure, report the re-run as a development
  result, not a held-out one (see `docs/RESULTS.md`).
- Keep pull requests small and include tests. `pytest` and `ruff` must pass.

## Useful commands

```bash
python -m eval.live payment --blind      # inject a fault, diagnose, approve, fix, verify
python -m eval.ablation                  # paired comparison against a naive LLM-plus-logs baseline
python -m eval.redteam                   # prompt-injection suite (offline)
python site/build_data.py                # rebuild the demo website's data from recorded runs
```
