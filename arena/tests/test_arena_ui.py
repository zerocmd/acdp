"""UI files: served by the app, and the store handles every event type the runtime emits."""

import re
from pathlib import Path

from conftest import SOC, make_arena, make_cast
from fastapi.testclient import TestClient

from arena.api import register_routes

UI = Path(__file__).resolve().parents[1] / "ui"


def test_ui_files_are_served(tmp_path):
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    register_routes(arena, UI, tmp_path)
    client = TestClient(arena.app)
    index = client.get("/").text
    assert "cdn.jsdelivr.net/npm/force-graph@1" in index
    assert '<script type="module" src="/ui/app.js">' in index
    for name in ("app.js", "graph.js", "transcript.js", "controls.js", "style.css"):
        assert client.get(f"/ui/{name}").status_code == 200, name


ARENA = Path(__file__).resolve().parents[1]


def emitted_event_types():
    """Every event type the runtime publishes, read from the source."""
    found = set()
    for path in ARENA.glob("*.py"):
        found.update(re.findall(r'publish\(\s*"([a-z_]+\.[a-z_]+)"', path.read_text()))
    return found


def test_store_handles_every_emitted_event_type():
    source = (UI / "store.js").read_text()
    handled = set(re.findall(r'"([a-z_]+\.[a-z_]+)"', source.split("];", 1)[0]))
    emitted = emitted_event_types()
    assert "registration.step" in emitted and "bus.reset" in emitted
    assert emitted - handled == set()
