"""ACDP agent entrypoint.

Runs one ACDP node: a Strands agent served over A2A (Agent Card at
/.well-known/agent-card.json, JSON-RPC at /) plus the ACDP REST surface
(/metadata, /peers, /health, /chat, /assist, /memory, ...).

    python agent.py              # uvicorn on AGENT_PORT
    uvicorn agent:app --port 8000
"""

import logging
import os

import uvicorn

from config import AGENT_CONFIG
from node import AgentNode

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
for noisy in ("httpx", "httpcore", "urllib3", "anthropic"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

if not os.environ.get("ANTHROPIC_API_KEY") and AGENT_CONFIG["model"]["provider"] == "anthropic":
    logger.error("ANTHROPIC_API_KEY is not set; model calls will fail")

node = AgentNode(AGENT_CONFIG)
app = node.build_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=AGENT_CONFIG["port"])
