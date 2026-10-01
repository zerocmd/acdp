"""Process entrypoint: live versus replay-only startup."""

import pytest

from arena.__main__ import create_arena, has_model_credentials, make_model_factory


def test_replay_only_without_credentials(tmp_path):
    arena, live = create_arena({"ARENA_RUNS_DIR": str(tmp_path)})
    assert live is False
    assert arena.bus.log_path is None
    assert any(getattr(r, "path", "") == "/ws" for r in arena.app.routes)


def test_live_with_anthropic_key_logs_to_runs_dir(tmp_path):
    arena, live = create_arena({"ANTHROPIC_API_KEY": "x", "ARENA_RUNS_DIR": str(tmp_path)})
    assert live is True
    assert arena.bus.log_path.parent == tmp_path
    assert arena.bus.log_path.suffix == ".jsonl"


def test_credentials_rules():
    assert has_model_credentials({"ANTHROPIC_API_KEY": "x"})
    assert has_model_credentials({"MODEL_PROVIDER": "bedrock"})
    assert not has_model_credentials({})


def test_bedrock_requires_tier_model_ids():
    factory = make_model_factory({"MODEL_PROVIDER": "bedrock"})
    with pytest.raises(ValueError, match="MODEL_ID_SONNET"):
        factory("sonnet", "x")


def test_real_server_accepts_websocket_connections(tmp_path):
    """TestClient does not need a WebSocket library; a real uvicorn server does."""
    import asyncio
    import socket
    import threading
    import time

    import uvicorn
    from websockets.sync.client import connect

    arena, _ = create_arena({"ARENA_RUNS_DIR": str(tmp_path)})
    arena.bus.publish("arena.idle", {"reason": "test"}, persist=False)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(arena.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        with connect(f"ws://127.0.0.1:{port}/ws", open_timeout=5) as ws:
            assert '"arena.idle"' in ws.recv(timeout=5)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
