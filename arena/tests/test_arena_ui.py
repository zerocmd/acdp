"""UI files: served by the app, and app.js handles every event type the runtime emits."""

from pathlib import Path

from conftest import SOC, make_arena, make_cast
from fastapi.testclient import TestClient

from arena.api import register_routes

UI = Path(__file__).resolve().parents[1] / "ui"
EVENT_TYPES = [
    "bus.reset", "arena.started", "arena.idle", "arena.paused", "arena.resumed",
    "arena.stopped", "agent.registered", "agent.verified", "agent.verification_failed",
    "agent.error", "discovery.query", "thread.opened", "thread.closed", "message.sent",
    "message.failed", "verification.peer_check", "decision.rejected",
]


def test_ui_files_are_served(tmp_path):
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    register_routes(arena, UI, tmp_path)
    client = TestClient(arena.app)
    index = client.get("/").text
    assert "cdn.jsdelivr.net/npm/force-graph@1" in index
    assert '<script type="module" src="/ui/app.js">' in index
    for name in ("app.js", "graph.js", "transcript.js", "controls.js", "style.css"):
        assert client.get(f"/ui/{name}").status_code == 200, name


def test_app_handles_every_event_type():
    source = (UI / "app.js").read_text()
    missing = [t for t in EVENT_TYPES if f'"{t}"' not in source]
    assert missing == []
