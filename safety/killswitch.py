from __future__ import annotations

from pathlib import Path


class KillSwitch:
    """File-backed so it survives restarts and can be tripped from any process."""

    def __init__(self, path: Path = Path(".killswitch")) -> None:
        self._path = path

    def engaged(self) -> bool:
        return self._path.exists()

    def engage(self) -> None:
        self._path.write_text("engaged", encoding="utf-8")

    def release(self) -> None:
        self._path.unlink(missing_ok=True)
