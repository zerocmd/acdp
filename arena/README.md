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

## Step 5: Open the Workbench

Open <http://localhost:8080>. The Workbench has five areas:

| Area | What it shows |
| --- | --- |
| Top bar | The run mode (`live`, `replay`, `idle`, `stopped`), counts of agents, messages, and open threads, **Pause**/**Resume**, the replay controls, and **+ Agent**. |
| Sidebar (left) | The agents, grouped by company, with a status dot (green verified, amber pending, red failed) and a model badge (`S` Sonnet, `H` Haiku). Below it, a registry summary. Click an agent to open its details. |
| View area (center) | Five views. Switch between them with the buttons above the area. |
| Timeline (below the view) | Four lanes: Register, Discover, Verify, and Message. Each dot is one event. Hover a dot for a summary. Click it to open the agent. Drag across the strip to set a time range; the views and the chat then show only that range. |
| Right column | The chat, or the agent drawer when an agent is selected. |

Press Esc to clear the selection and the time range.

### Views

| View | Use it to see |
| --- | --- |
| Network | Who talks to whom. Each company is an outline with a small label. Each pair of agents has one edge per thread; red edges are declines and challenges. During a discovery search, the searcher gets a purple ring and dashed purple lines to each result, for about 2 seconds. Results that are new to the searcher show "new". Select **show every search** to highlight every query, not only queries with new results. |
| Sequence | The order of events. One lane per agent; time flows down. Arrows are messages, labelled with their intent. Purple diamonds are discovery searches; green diamonds are verification checks. Brackets on the requester's lane show A2A tasks from request to answer. |
| Flow | The shape of one thread, left to right from the agent that opened it. Replies and loops curve back as dashed lines. |
| Matrix | Senders (rows) by recipients (columns). Darker cells mean more messages. A red border means the recipient's trust check failed. Click a cell to show only that pair in the chat. |
| Registry | The registry's entries. Search and filter by status. Expand a row to see each verification check, the stored entry, and the stored card next to the live card. The **Organizations** tab shows which domain anchors each organization name. |

### Chat

The chat shows one thread at a time. Pick a thread with the chips at the top, or click **All threads** to see every message in time order. Each message shows the sender, company, domain, recipient, intent, and the recipient's trust check. A purple line shows what the sender was looking for and why it picked this peer. A message that failed the trust check has a dashed red border. A request shows the state of its A2A task: `working`, `completed`, `rejected`, or `canceled`.

### Agent drawer

| Tab | What it shows |
| --- | --- |
| Overview | Role, capability, needs, cadence, state, counters, the seven registration steps (identity, zone, DNS, card, submitted, registry checks, result), and the DNS records as published. |
| Card | The live Agent Card: a summary and the raw JSON. If the live card is not available, the stored registry card. |
| Prompts | The system prompt, the last turn prompt as the model received it, and the last decision with its outcome. |
| Activity | The agenda, the agent's threads, its pending inbox (live runs only), its recent decisions, and its A2A tasks. |
| Discovery | Each search with its results and their registry status, the peers the agent chose and why, and its trust map. |

In a replay, data that only a live agent can give shows "Not available in replay".

### Make a demo run without credits

```bash
PYTHONPATH=agent:. python arena/scripts/make_demo_log.py
```

The script writes `runs/demo.jsonl` from a scripted run: no model calls and no network. Select `demo` in the replay controls and click **Replay**.

Run logs include the full turn prompt of every decision. A 20-minute live run makes a log of about 5 to 10 MB.

## Step 6: Watch the run

What to look for:

1. The SOC Investigator (Northgate Bank) gets the incident brief and opens thread `t1`.
2. Threat intel, identity, network, and peer SOC agents share findings on `t1`.
3. The impostor sends its first message after 2 to 3 minutes. Peers see `trust=failed (domain mismatch)` and send `decline` or `challenge`. The UI shows these in red.
4. The ISAC Coordinator closes `t1` with a `verdict` after at least three investigation agents have shared findings.
5. The procurement, exposure, and sales agents run their own threads at the same time.

In the Network view, watch for discovery: when an agent searches the registry, purple lines connect it to each result. After you add an agent, the next search by an agent that needs its capability marks it "new".

Click **Pause** to freeze all agents. Click **Resume** to continue.

## Step 7: Add an agent while the arena runs

You can add an agent from the UI or with an HTTP request. Both use the same inputs. The arena gives the agent a new key, publishes its DNS records, registers it, and starts its loop. You do not need to restart anything.

### Inputs

| Input (UI field / JSON key) | Required | Rules | What it is for |
| --- | --- | --- | --- |
| **Name** / `name` | Yes | 1 to 60 characters | The display name in the graph and transcript. The arena also makes the agent's short name (slug) from it. For example, `Northwind Intel` becomes `northwind-intel`. The slug must not already be in use. |
| **Organization** / `organization` | Yes | 1 to 80 characters | The company that the agent claims to belong to. The registry anchors each organization name to the first domain that registers it. If you use the name of an existing organization with a different domain, the agent fails verification, as the impostor does. |
| **Domain** / `domain` | Yes | A DNS name that ends with `.example`, `.local`, `extrahop.com`, or `tenable.com` | The company domain. The arena creates a DNS zone for it if none exists, and publishes the agent's records and key pin there. The agent id is `<slug>.<domain>`, for example `northwind-intel.northwind.example`. |
| **Capability** / `capability` | Yes | Lowercase letters, digits, and hyphens, 1 to 40 characters | What the agent offers. Other agents search the registry by capability. They find the new agent only if their own needs include this capability. |
| **Needs** / `needs` | No | Comma-separated in the UI; a list in JSON | The capabilities the new agent looks for on each turn. These decide which peers it can start a conversation with. With no needs, it can only reply to agents that message it first. |
| **Model** / `model` | No | `haiku` (default) or `sonnet` | The Claude model that makes the agent's decisions. Sonnet is better at weighing evidence. Haiku is faster and costs less. |
| **Agenda** / `agenda` | Yes, unless Generate is on | Up to 1,000 characters | What the agent wants to achieve. When Generate is off, the agenda is the agent's system prompt, so write it in the second person ("You ..."). When Generate is on, Sonnet uses the agenda as input. |
| **Generate prompt with Sonnet** / `generate` | No | `true` or `false` (default) | Asks Sonnet to write a system prompt from the name, organization, capability, and agenda. This adds one Sonnet call. |
| **Misconfigure** / `misconfigure` | No | `none` (default), `no_txt`, or `wrong_key` | Breaks the agent on purpose to show a failed verification. `no_txt` publishes no DNS TXT record. `wrong_key` publishes the fingerprint of a different key. |

Every added agent takes a turn every 40 to 60 seconds.

### Example

This example adds a threat intelligence agent from a new company. The SOC agents need `threat-intel`, so they find the new agent on their next turn.

| Field | Value |
| --- | --- |
| Name | `Northwind Intel` |
| Organization | `Northwind Threat Labs` |
| Domain | `northwind.example` |
| Capability | `threat-intel` |
| Needs | `soc-investigation, coordination` |
| Model | `Haiku` |
| Agenda | `You track phishing kits sold on criminal forums. Offer SOC teams indicators that match their sender domains. Share your findings with the ISAC.` |
| Generate prompt with Sonnet | off |
| Misconfigure | `None` |

**In the UI:**

1. Click **Add agent**.
2. Fill in the fields from the table.
3. Click **Add**.

**With an HTTP request:**

```bash
curl -s -X POST localhost:8080/arena/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Northwind Intel",
    "organization": "Northwind Threat Labs",
    "domain": "northwind.example",
    "capability": "threat-intel",
    "needs": ["soc-investigation", "coordination"],
    "model": "haiku",
    "agenda": "You track phishing kits sold on criminal forums. Offer SOC teams indicators that match their sender domains. Share your findings with the ISAC.",
    "generate": false,
    "misconfigure": "none"
  }'
```

The response is `201` with the new agent's id and slug:

```json
{"id": "northwind-intel.northwind.example", "slug": "northwind-intel"}
```

### What you see

1. A new node appears in its own cluster, labelled `Northwind Threat Labs (northwind.example)`, with an amber border.
2. The border turns green when the registry verifies the agent.
3. Within about 20 seconds, the SOC agents' discovery includes `northwind-intel.northwind.example`.
4. The new agent takes its first turn after 40 to 60 seconds.

### Show a failed verification

Use the same example with **Misconfigure** set and a new name, for example `Northwind Intel 2`:

- **Missing TXT record** (`no_txt`): the node turns red. The transcript shows `failed verification: txt record missing`.
- **Wrong key in DNS** (`wrong_key`): the node turns red. The transcript shows `failed verification: key mismatch`.

To show the impostor pattern, set **Organization** to `Halcyon Intel` and **Domain** to `halcyon-intel-labs.example`. The transcript shows `failed verification: organization registered under halcyon-intel.example`.

### Errors

| Response | Cause |
| --- | --- |
| `400` `agenda or generate is required` | The agenda is empty and Generate is off. |
| `400` `slug '...' is invalid or in use` | Another agent already has a name that makes the same slug. Choose another name. |
| `400` `invalid domain` or `zone must end with ...` | The domain is not a valid DNS name, or it is not under an allowed suffix. |
| `422` | A field breaks a rule in the Inputs table, for example a capability with uppercase letters or a model other than `haiku` or `sonnet`. |
| `502` `prompt generation failed` | Generate is on and the Sonnet call failed. Try again, or turn Generate off and write the agenda yourself. |

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

The UI has its own tests for the event store and the layout helpers. They need Node 22 or later:

```bash
node --test "arena/ui/tests/*.test.mjs"
```

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
