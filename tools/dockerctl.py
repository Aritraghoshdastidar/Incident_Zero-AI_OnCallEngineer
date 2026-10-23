"""Container-level fault injection and the matching approved remediations.

Used by the held-out evaluation (infrastructure faults that have no feature flag, so the agent cannot
solve them from the demo's documented flag names) and by the `restore_resources` runbook.
Original resource limits are snapshotted before the first change so restore is exact.
"""
from __future__ import annotations

import json
import subprocess
import sys

from .config import DOCKER, ROOT

BASELINE = ROOT / "data" / "docker.baseline.json"


def _docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=120)


def _limits(container: str) -> dict:
    out = _docker("inspect", "--format", "{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}", container).stdout.strip()
    mem, nano = out.split("|")
    return {"memory": int(mem), "nano_cpus": int(nano)}


def _snapshot(container: str) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    data.setdefault(container, _limits(container))
    BASELINE.write_text(json.dumps(data))


def stop(container: str) -> None:
    _docker("stop", container)


def start(container: str) -> None:
    _docker("start", container)


def limit_memory(container: str, mb: int) -> None:
    _snapshot(container)
    _docker("update", "--memory", f"{mb}m", "--memory-swap", f"{mb}m", container)


def limit_cpu(container: str, cpus: float) -> None:
    _snapshot(container)
    _docker("update", "--cpus", str(cpus), container)


def ncpu() -> int:
    return int(_docker("info", "--format", "{{.NCPU}}").stdout.strip() or 1)


def restore(container: str) -> None:
    base = json.loads(BASELINE.read_text())[container]
    mem = base["memory"]
    # `docker update --cpus 0` does not clear a limit; the host CPU count is the effective "unlimited".
    cpus = base["nano_cpus"] / 1e9 or float(ncpu())
    _docker("update", "--memory", str(mem), "--memory-swap", str(mem) if mem else "-1", "--cpus", str(cpus), container)
    _docker("start", container)  # a memory-killed container may need starting again


def container_states() -> list[dict]:
    """State of every container (including stopped ones): the infra view an on-call engineer has."""
    names = _docker("ps", "-a", "--format", "{{.Names}}").stdout.split()
    host_cpus, rows = ncpu(), []
    for n in names:
        out = _docker("inspect", "--format",
                      "{{.State.Status}}|{{.State.OOMKilled}}|{{.State.ExitCode}}|{{.RestartCount}}|"
                      "{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|{{.State.StartedAt}}", n).stdout.strip()
        status, oom, code, restarts, mem, nano, started = out.split("|")
        rows.append({"service": n, "status": status, "oom_killed": oom == "true", "exit_code": int(code),
                     "started_at": started,
                     "restart_count": int(restarts), "memory_limit_mb": round(int(mem) / 1e6) or None,
                     # a limit at/above the host's CPU count is no limit at all
                     "cpu_limit": round(int(nano) / 1e9, 3) if 0 < int(nano) / 1e9 < host_cpus else None})
    return rows


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"stop": stop, "start": start, "restore": restore}[cmd](*args)
