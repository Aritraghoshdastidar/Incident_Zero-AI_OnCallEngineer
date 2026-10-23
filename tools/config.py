from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "otel-demo"
FLAGS_FILE = DEMO_DIR / "src" / "flagd" / "demo.flagd.json"
FLAGS_BASELINE = ROOT / "data" / "flags.baseline.json"

# 127.0.0.1, not localhost: on Windows localhost resolves to IPv6 first and Docker's proxy drops it.
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")
ENVOY_URL = os.getenv("ENVOY_URL", "http://127.0.0.1:8080")
JAEGER_URL = os.getenv("JAEGER_URL", f"{ENVOY_URL}/jaeger/ui")

DOCKER = shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
