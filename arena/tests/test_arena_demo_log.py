"""The demo log script produces every event family the Workbench shows."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_demo_log_contains_the_workbench_event_families(tmp_path):
    out = tmp_path / "demo.jsonl"
    env = dict(os.environ, PYTHONPATH=f"{ROOT / 'agent'}{os.pathsep}{ROOT}")
    env.pop("ANTHROPIC_API_KEY", None)
    subprocess.run([sys.executable, str(ROOT / "arena/scripts/make_demo_log.py"), "--out", str(out)],
                   check=True, env=env, cwd=ROOT)
    events = [json.loads(line) for line in out.read_text().splitlines()]
    types = {e["type"] for e in events}
    assert {"registration.step", "discovery.query", "decision.made", "message.sent",
            "verification.peer_check", "thread.closed", "arena.stopped"} <= types
    gaps = {round(b["ts"] - a["ts"], 3) for a, b in zip(events, events[1:])}
    assert gaps == {2.0}
