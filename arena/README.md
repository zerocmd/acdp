# Running the ACDP Agent Arena

This guide shows how to start the arena, watch a run, add an agent while the arena runs, and replay a saved run.

The arena runs ten LLM agents from different organizations. The agents find each other through ACDP, check each other with DNS-pinned Ed25519 keys, and talk over A2A. One agent is an impostor that uses the lookalike domain `halcyon-inte1.example`. The other agents detect it and decline it. For the design, see [the spec](../docs/superpowers/specs/2026-10-01-acdp-agent-arena-design.md).

## What runs

| Service | Port | Purpose |
| --- | --- | --- |
| `bind` | 53 (DNS), 8053 (DNS API) | BIND9. Holds one DNS zone for each company domain and the TXT key pins. |
| `registry` | 5001 | ACDP registry. Checks each Agent Card against DNS and records the result. |
| `arena` | 8080 | The ten agents, the event stream, and the browser UI. |

## Before you start

You need:

- Docker Desktop (or Docker Engine) with Compose v2. Check with `docker compose version`.
- An Anthropic API key for a live run. You do not need a key to replay a saved run.
- Free ports 53, 5001, 8053, and 8080 on your machine.
- Network access for the first build. The build pulls base images and installs packages.

A live run calls Claude models and costs credits. By default, a run stops after 20 minutes or 600 model decisions, whichever comes first.

## Step 1: Get the code

```bash
git clone https://github.com/zerocmd/acdp.git
cd acdp
```

## Step 2: Set your API key

```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

To use smaller limits, set them before you start:

```bash
export ARENA_MAX_MINUTES=10        # default 20
export ARENA_MAX_MODEL_CALLS=200   # default 600
```

## Step 3: Build and start the stack

```bash
docker compose up -d --build
```

The first build takes a few minutes. Later builds use the Docker cache.

## Step 4: Check that the services are up

```bash
docker compose ps
curl -s localhost:5001/health
```

All three services show `running`. The registry shows `healthy`. The health call returns `{"agent_count":10,"status":"ok"}` after the agents register.

Check the verification results:

```bash
curl -s localhost:5001/agents | python3 -m json.tool | grep -c '"status": "verified"'
```

The command prints `9`. Nine agents pass verification. The impostor fails with the reason `organization registered under halcyon-intel.example`.

To see a key pin in DNS:

```bash
dig @localhost _llm-agent._tcp.halcyon-intel.halcyon-intel.example TXT +short
```

The TXT record includes `key=` followed by a 43-character fingerprint.

## Step 5: Open the UI

Open <http://localhost:8080>.

- **Graph (left):** one node for each agent, grouped by domain. `S` means Sonnet and `H` means Haiku. The border shows verification: green is verified, amber is pending, and red is failed. An animated edge shows each message, in the color of its thread.
- **Transcript (right):** every message with sender, recipient, thread color, and intent. Gray lines show registration, verification, and thread events. Use the filters to show one thread, agent, company, or intent. Click a node to filter to that agent. Click **Clear** to show everything again.
- **Control bar (top):** counts of agents, messages, and open threads, the **Pause** button, the replay controls, and **Add agent**.

## Step 6: Watch the run

What to look for:

1. The SOC Investigator (Northgate Bank) gets the incident brief and opens thread `t1`.
2. Threat intel, identity, network, and peer SOC agents share findings on `t1`.
3. The impostor sends its first message after 2 to 3 minutes. Peers see `trust=failed (domain mismatch)` and send `decline` or `challenge`. The UI shows these in red.
4. The ISAC Coordinator closes `t1` with a `verdict` after at least three investigation agents have shared findings.
5. The procurement, exposure, and sales agents run their own threads at the same time.

Click **Pause** to freeze all agents. Click **Resume** to continue.

## Step 7: Add an agent while the arena runs

1. Click **Add agent**.
2. Enter a name, organization, domain, and capability. The domain must end with `.example` or `.local`, for example `coastal-bank.example`. The capability must use lowercase letters, digits, and hyphens.
3. In **Needs**, enter the capabilities the new agent looks for, for example `soc-investigation`.
4. Enter an agenda. Or select **Generate prompt with Sonnet** to let Sonnet write the system prompt.
5. Click **Add**.

The new node appears in its own cluster and turns green when the registry verifies it. Other agents find it on their next discovery query if they need its capability. For example, a new `threat-intel` agent is found by the SOC agents.

To show a failed verification, set **Misconfigure**:

- **Missing TXT record**: the registry reports `txt record missing`.
- **Wrong key in DNS**: the registry reports `key mismatch`.

## Step 8: Replay a saved run

Each live run writes its events to `runs/<run-id>.jsonl` in the repository folder.

1. Select a run in the drop-down list in the control bar.
2. Set the speed with the slider (1x to 10x).
3. Click **Replay**.

Replay stops the live run. To start a new live run, restart the arena with `docker compose restart arena`.

You do not need an API key to replay. Without a key, the arena starts in replay-only mode, and the mode label shows `idle`.

## Step 9: Stop the stack

```bash
docker compose down
```

To also delete the DNS zones and start the next run with a clean DNS server:

```bash
docker compose down -v
```

The run logs in `runs/` stay on disk.

## Free dry run

To check the whole stack without model calls, set the call limit to zero:

```bash
ARENA_MAX_MODEL_CALLS=0 docker compose up -d --build
```

All ten agents register and the registry verifies them. The arena then stops before any agent makes a model call. Steps 4 and 5 work as normal. The run log shows `arena.stopped` with the reason `model call limit reached`.

## Run the arena without Docker

Use this mode to work on the UI. It runs the arena process on your machine in replay-only mode.

```bash
pip install -r requirements.txt
mkdir -p runs
env -u ANTHROPIC_API_KEY PYTHONPATH=agent:. ARENA_RUNS_DIR=runs python -m arena
```

Open <http://localhost:8080>, put a saved run in `runs/`, and replay it. A live run needs the DNS and registry services, so use Docker for live runs.

## Run the tests

```bash
pip install -r requirements.txt
pytest
```

The tests need no API key, no containers, and no network.

To check a live run (this costs credits), start the stack and run:

```bash
python arena/scripts/smoke.py --minutes 5
```

The script reads the newest run log and checks three things: messages on thread `t1`, a `decline` or `challenge` sent to the impostor, and no `agent.error` events.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | unset | Model access. Without it, the arena starts in replay-only mode. |
| `MODEL_PROVIDER` | `anthropic` | `anthropic` or `bedrock`. Bedrock needs `MODEL_ID_SONNET`, `MODEL_ID_HAIKU`, and AWS credentials. |
| `ARENA_MAX_MINUTES` | `20` | Time limit for a run. |
| `ARENA_MAX_MODEL_CALLS` | `600` | Limit on model decisions for a run. |
| `REGISTRY_CARD_HOSTS` | `arena` | Hosts that the registry can fetch Agent Cards from. Compose sets it. |

## Troubleshooting

| Problem | Cause and fix |
| --- | --- |
| `bind` does not start: port 53 is in use | Another DNS service uses port 53. Stop that service, or remove the `53:53` port lines from the `bind` service in `docker-compose.yml`. The arena does not need port 53 on the host. |
| The `bind` build fails at `apt-get` | The base image must be `ubuntu/bind9:9.18-24.04_beta`. The `latest` tag uses an Ubuntu release whose package archive was removed. Check the first `FROM` line of `dns/DockerFile`. |
| `bind` runs old code after a change | Compose can reuse a stale image when a build fails. Run `docker compose build --no-cache bind`, then `docker compose up -d --force-recreate bind`. |
| The UI mode label stays at `reconnecting` | The WebSocket at `/ws` does not connect. Read `docker compose logs arena`. A message about a missing WebSocket library means the image is out of date. Rebuild with `docker compose build arena`. |
| An agent shows a red border that you did not expect | Read its reasons in the transcript, or run `curl -s localhost:5001/agents`. `txt record missing` and `key mismatch` point to DNS. Run `docker compose down -v` and start again for a clean DNS server. |
| No agents appear | The arena has no model credentials and is in replay-only mode. Set `ANTHROPIC_API_KEY` and run `docker compose up -d --force-recreate arena`. |
