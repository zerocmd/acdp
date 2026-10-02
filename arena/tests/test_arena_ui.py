"""UI files: served by the app, and the store handles every event type the runtime emits."""

import re
from pathlib import Path

from conftest import SOC, make_arena, make_cast
from fastapi.testclient import TestClient

from arena.api import register_routes

UI = Path(__file__).resolve().parents[1] / "ui"


UI_FILES = ["preact.js", "api.js", "app.js", "store.js", "palette.js", "style.css",
            "components/topbar.js", "components/sidebar.js", "components/viewswitch.js",
            "components/legend.js", "components/addagent.js", "components/chat.js",
            "views/commsmap.js", "components/timeline.js", "lib/layout.js",
            "components/drawer.js", "components/steps.js",
            "components/registry.js", "lib/diff.js", "views/sequence.js",
            "components/popup.js", "views/mapfx.js", "lib/chord.js", "views/chord.js", "views/matrix.js", "lib/textscale.js",
            "components/cards.js", "components/textsize.js"]


def test_ui_files_are_served(tmp_path):
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    register_routes(arena, UI, tmp_path)
    client = TestClient(arena.app)
    index = client.get("/").text
    for url in ("force-graph", "dagre"):
        assert url not in index, url
    assert 'import("/ui/app.js")' in index
    assert "htm@3/preact/standalone.module.js" in (UI / "preact.js").read_text()
    for name in UI_FILES:
        assert client.get(f"/ui/{name}").status_code == 200, name
    for old in ("graph.js", "transcript.js", "controls.js", "views/network.js",
                "views/flow.js"):
        assert not (UI / old).exists(), old


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


def test_ui_is_served_with_no_cache(tmp_path):
    """Browsers must revalidate UI modules, or an upgrade mixes old and new code."""
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"))
    register_routes(arena, UI, tmp_path)
    client = TestClient(arena.app)
    for path in ("/", "/ui/store.js", "/ui/components/chat.js"):
        assert client.get(path).headers.get("cache-control") == "no-cache", path
