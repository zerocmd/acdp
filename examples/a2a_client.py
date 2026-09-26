"""Discover an agent through ACDP, then call it with a plain A2A client.

Shows that ACDP agents are ordinary A2A servers: the registry answers "who can do X",
the Agent Card says how to talk to them, and any A2A client can make the call.

    pip install 'a2a-sdk>=0.3,<0.4' httpx requests
    python examples/a2a_client.py --capability log_analysis \
        --question "What are common signs of lateral movement in Windows logs?"

Agent Cards advertise Docker-network URLs (http://agent3:8000/). From the host, pass
--port-map so the client uses the published ports instead.
"""

import argparse
import asyncio
import uuid

import httpx
import requests
from a2a.client import ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Part, Role, Task, TextPart

# docker-compose.yml host port for each agent service
DEFAULT_PORT_MAP = {"agent1": 8001, "agent2": 8002, "agent0": 8003, "agent4": 8004, "agent3": 8005}


def text_of(event) -> str:
    if isinstance(event, Message):
        return "".join(p.root.text for p in event.parts if isinstance(p.root, TextPart))
    if isinstance(event, tuple) and isinstance(event[0], Task):
        task = event[0]
        text = "".join(
            p.root.text
            for artifact in task.artifacts or []
            for p in artifact.parts
            if isinstance(p.root, TextPart)
        )
        if text:
            return text
        status = task.status.message.parts if task.status.message else []
        detail = "".join(p.root.text for p in status if isinstance(p.root, TextPart))
        return f"[task {task.status.state.value}] {detail}".strip()
    return ""


async def ask(card: AgentCard, question: str, token: str | None) -> str:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with httpx.AsyncClient(timeout=300, headers=headers) as http:
        client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
        message = Message(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=question))],
        )
        final = None
        async for event in client.send_message(message):
            final = event
        return text_of(final)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="http://localhost:5001")
    parser.add_argument("--capability", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--token", help="ACDP_A2A_TOKEN, if the network requires one")
    parser.add_argument(
        "--no-port-map", action="store_true", help="use Agent Card URLs as-is (inside the network)"
    )
    args = parser.parse_args()

    agents = requests.get(
        f"{args.registry}/agents",
        params={"capability": args.capability, "protocol": "a2a", "status": "online"},
        timeout=10,
    ).json()["agents"]
    if not agents:
        raise SystemExit(f"No online A2A agent with capability {args.capability!r}")
    chosen = agents[0]
    print(f"ACDP registry -> {chosen['name']} ({chosen['id']})")

    card = AgentCard.model_validate(
        requests.get(f"{args.registry}/agents/{chosen['id']}/card", timeout=10).json()
    )
    if not args.no_port_map:
        service = httpx.URL(card.url).host
        if service in DEFAULT_PORT_MAP:
            card.url = f"http://localhost:{DEFAULT_PORT_MAP[service]}/"
    print(f"A2A endpoint  -> {card.url} (skills: {', '.join(s.id for s in card.skills)})\n")

    print(asyncio.run(ask(card, args.question, args.token)))


if __name__ == "__main__":
    main()
