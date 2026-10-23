# Run inside an activated virtual environment, or point PY at one:  make test PY=.venv/bin/python
PY ?= python

.PHONY: test lint dashboard demo report site-data

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

dashboard:
	$(PY) -m uvicorn ui.app:app --port 8765

# Inject a fault, then diagnose and wait for approval in the dashboard (run `make dashboard` first).
demo:
	$(PY) -m tools.flagctl set paymentFailure 100%
	sleep 120
	$(PY) -m agent.run "Customers cannot complete payment at checkout" --dashboard

report:
	$(PY) -m report.incident

# Rebuild the demo website's data from the recorded runs (needs the demo stack up for Prometheus history).
site-data:
	$(PY) site/build_data.py
