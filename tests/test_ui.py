import threading
import time
import types

from fastapi.testclient import TestClient

from ui import approver
from ui.app import app


def _card(iid="inc-test1"):
    return types.SimpleNamespace(incident_id=iid, render=lambda: "card", __dict__={"incident_id": iid, "risk": "low"})


def test_approve_flow_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(approver, "PENDING", tmp_path / "p")
    monkeypatch.setattr(approver, "DECISIONS", tmp_path / "d")
    import ui.app as ui_app
    monkeypatch.setattr(ui_app, "PENDING", tmp_path / "p")
    monkeypatch.setattr(ui_app, "DECISIONS", tmp_path / "d")
    client = TestClient(app)
    result = {}
    th = threading.Thread(target=lambda: result.update(ok=approver.file_approver(_card(), timeout_s=10, poll_s=0.1)))
    th.start()
    for _ in range(50):
        if client.get("/api/pending").json():
            break
        time.sleep(0.1)
    assert client.get("/api/pending").json()[0]["incident_id"] == "inc-test1"
    assert client.post("/api/decision/inc-test1", json={"approve": True}).status_code == 200
    th.join(5)
    assert result["ok"] is True


def test_timeout_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(approver, "PENDING", tmp_path / "p")
    monkeypatch.setattr(approver, "DECISIONS", tmp_path / "d")
    assert approver.file_approver(_card("inc-test2"), timeout_s=1, poll_s=0.2) is False


def test_rejects_path_traversal_incident_id():
    client = TestClient(app)
    assert client.post("/api/decision/..%2f..%2fetc", json={"approve": True}).status_code in (400, 404)
    assert client.post("/api/decision/not$valid", json={"approve": True}).status_code == 400
