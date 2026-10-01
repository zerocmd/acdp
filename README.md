# Agent Communication & Discovery Protocol PoC

This proof of concept implements the [Agent Communication & Discovery Protocol](ACDP.md), allowing AI agents to register, discover, communicate with each other, and share memory. Agents are built with the [Strands Agents SDK](https://strandsagents.com/) and talk to each other over the [Agent2Agent (A2A) protocol](https://a2a-protocol.org/): ACDP finds the right peer (DNS, registry, gossip), A2A carries the request. It uses a cybersecurity scenario (see agent capabilities); each agent's model decides when a question needs a specialist peer and consults it.

This implementation is an example that visualises the approaches in the specification. It is not comprehensive: transport is plain HTTP inside the Docker network and most of the security options in the specification are not implemented. See [docs/STRANDS_A2A_REVISION.md](docs/STRANDS_A2A_REVISION.md) for the design of the Strands/A2A revision.

## Components

- **DNS Server (BIND9)**: DNS-based discovery with SRV and TXT records. TXT records carry `a2a=` (Agent Card path) and `proto=` keys for ACDP 1.1 agents.
- **Central Registry**: Flask service for agent registration, discovery, heartbeats, stored A2A Agent Cards, and shared memory.
- **Agents**: [Strands Agents](https://strandsagents.com/) (Anthropic Claude by default, Amazon Bedrock optional). Each agent is an A2A server (Agent Card at `/.well-known/agent-card.json`, JSON-RPC at `/`) and also serves the ACDP REST API (`/metadata`, `/peers`, `/chat`, ...). Peers are consulted through model tools: `find_agents` (ACDP discovery) and `ask_agent` (A2A call with a bounded delegation trace).

## Setup

You will require a BIND server as a Docker image: [BIND 9](https://hub.docker.com/r/ubuntu/bind9/)

1. Clone this repository
2. Set your Anthropic API key:

   ```bash
   export ANTHROPIC_API_KEY=your_api_key_here
   ```

   Optional settings (defaults in brackets):

   | Variable | Purpose |
   | --- | --- |
   | `MODEL_PROVIDER` [`anthropic`] | `anthropic` or `bedrock` (Bedrock needs `MODEL_ID` and AWS credentials/region) |
   | `MODEL_ID` [`claude-sonnet-5-5`] | Model for every agent |
   | `COLLABORATION_MODE` [`auto`] | `auto`: the model decides when to consult peers; `always`: consult at least one relevant peer per question; `off`: no peer tools |
   | `ACDP_MAX_DELEGATION_DEPTH` [`2`] | Longest agent-to-agent chain (A -> B -> C is 2) |
   | `ACDP_MAX_PEER_CALLS` [`4`] | Peer calls one request may make |
   | `ACDP_A2A_TOKEN` [unset] | Shared bearer token required on A2A JSON-RPC, `/assist`, `POST /memory`, `/gossip/start` and `/gossip/stop`. `/chat` stays open; restrict it at the network level |

3. Install dependencies (if not using Docker):

   ```bash
   pip install -r requirements.txt
   ```

4. Start the services:

   ```bash
   docker compose up -d --build
   ```

## Usage

### Registry Dashboard

View registered agents at: <http://localhost:5001>

### Test DNS Resolution

```bash
dig @localhost _llm-agent._tcp.agent1.agents.local SRV 
dig @localhost _llm-agent._tcp.agent1.agents.local TXT
```

### Interact with Agents

Agent 1: <http://localhost:8001/chat>
Agent 2: <http://localhost:8002/chat>
Agent 0: <http://localhost:8003/chat>
Agent 4: <http://localhost:8004/chat>
Agent 3: <http://localhost:8005/chat>

Example API call:

```bash
curl -X POST http://localhost:8001/chat -H "Content-Type: application/json" -d '{"text": "Hello, can you help me with something?"}'
```

When the agent consulted peers, the response includes `meta.peers` and `meta.transports` (`a2a`, or `rest-assist` for ACDP 1.0 peers).

### Talk to Agents over A2A

Every agent is a standard A2A server, so any A2A client can call it.

```bash
# Agent Card (includes the ACDP extension with the agent's ACDP id)
curl http://localhost:8005/.well-known/agent-card.json

# JSON-RPC message/send
curl -X POST http://localhost:8005/ -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0", "id": "1", "method": "message/send",
  "params": {"message": {"role": "user", "messageId": "m1",
    "parts": [{"kind": "text", "text": "What are common signs of lateral movement in Windows logs?"}]}}
}'
```

Discover through the registry, then call with the A2A Python SDK:

```bash
python examples/a2a_client.py --capability log_analysis \
  --question "What are common signs of lateral movement in Windows logs?"
```

Registry queries for A2A-capable agents:

```bash
curl "http://localhost:5001/agents?protocol=a2a&status=online"
curl "http://localhost:5001/agents?skill=threat_detection"
curl http://localhost:5001/agents/agent3.agents.local/card
```

### View Peer Information

```bash
curl http://localhost:8001/peers 
curl http://localhost:8001/metadata
```

### Shared Memory System

The system includes a shared memory feature allowing agents to store and retrieve information through the central registry.

#### Access Shared Memory

View all memory entries:

```bash
curl http://localhost:8001/memory
```

Get a specific memory entry:

```bash
curl http://localhost:8001/memory/agent_memory_agent1.agents.local
```

Add or update a memory entry:

```bash
curl -X POST http://localhost:8001/memory -H "Content-Type: application/json" -d '{
  "key": "shared_notes",
  "value": {"topic": "weather", "note": "It will rain tomorrow"},
  "owner": "agent1.agents.local"
}'
```

#### Web UI for Shared Memory

The registry dashboard provides a UI for viewing and managing shared memory at:
<http://localhost:5001>

Navigate to the "Shared Memory" tab to:

- View all memory entries
- Add new memory entries
- See which agent owns each memory entry

### Add another Agent

Agents are defined in `docker-compose.yml` and share the `x-agent` / `x-agent-env` blocks:

```yaml
  agent5:
    <<: *agent
    ports:
      - "8006:8000"
    environment:
      <<: *agent-env
      AGENT_ID: agent5.agents.local
      AGENT_NAME: Agent Analyzer
      AGENT_CAPABILITIES: security,threat_detection,attack_patterns
      AGENT_DESCRIPTION: AI assistant specializing in security analysis and threat detection
      AGENT_HOSTNAME: agent5.agents.local
```

## Architecture

This implementation follows the Agent Communication & Discovery Protocol specification with the ACDP 1.1 A2A profile:

1. Agents register with DNS (SRV + TXT, including `a2a=` and `proto=`) and with the central registry (metadata plus their A2A Agent Card)
2. Agents discover each other through the registry, DNS and gossip, and maintain peer lists
3. Agents call each other over A2A JSON-RPC; ACDP 1.0 peers are still reached through `/assist`
4. Each agent's Strands model decides when to consult peers, using `find_agents` and `ask_agent` tools
5. Delegation chains are bounded: every A2A message carries a hop count and trace in the ACDP extension metadata, and agents refuse cycles and over-long chains
6. Agents can store and retrieve information using the shared memory system, also exposed to the model as tools
7. Heartbeats maintain registry consistency; the registry reports agents as `online` or `stale`

### Shared Memory Architecture

The shared memory system follows a simple client-server model:

1. The **registry server** manages a central in-memory store
2. **Agents** use the registry client to read from and write to this store
3. Memory entries are stored as key-value pairs with metadata (owner, timestamp)
4. Agents automatically record chat interactions in memory for future reference

### Agent Collaboration

Agents collaborate through tools the model calls when it judges them useful:

1. **find_agents**: searches known peers and the registry by capability (ACDP capability or A2A skill) or keyword
2. **ask_agent**: resolves the peer through ACDP, fetches and checks its Agent Card, and sends the question over A2A (several calls in one turn run in parallel)
3. **read_shared_memory / write_shared_memory**: the registry's shared memory
4. The agent writes the final answer, attributing peer contributions by name
5. The interaction is recorded in shared memory

With `COLLABORATION_MODE=always` the prompt requires consulting at least one relevant peer per question, which is closest to the original PoC behaviour.

## Extensions

This proof of concept can be extended with:

- HTTPS/mTLS and signed Agent Cards (A2A `signatures`)
- OAuth2 or per-agent credentials instead of the shared `ACDP_A2A_TOKEN`
- A2A 1.0 once the Strands SDK supports it (see the revision document)
- MCP servers discovered through ACDP and attached to agents with the Strands MCP client
- DNSSEC for DNS security
- Persistent storage for the registry and shared memory

## Testing the Implementation

### Automated Tests

Unit and in-process integration tests need no API key or containers. The integration tests run several agents in one process with a scripted Strands model and route real A2A JSON-RPC between them.

```bash
pip install -r requirements.txt
pytest
```

The scripts in `agent/test_*.py` and `agent/monitor_collaboration.py` exercise a running `docker compose` deployment.

### Basic Tests

1. **Start the System**:

   ```bash
   docker compose up -d
   ```

   Check logs to verify all components start correctly:

   ```bash
   docker compose logs registry
   docker compose logs agent1
   docker compose logs agent2
   ```

2. **Registry Discovery Test**:
   - Access the registry dashboard to see registered agents:

     ```bash
     http://localhost:5001/
     ```

   - Query the registry API directly:

     ```bash
     curl http://localhost:5001/agents
     ```

3. **DNS Resolution Test**:
   - Use `dig` to query agent DNS records:

     ```bash
     dig @localhost -p 5353 _llm-agent._tcp.agent1.agents.local SRV
     dig @localhost -p 5353 _llm-agent._tcp.agent1.agents.local TXT
     ```

### Testing Collaboration

1. **Ask a Question to an Agent**:

   ```bash
   curl -X POST http://localhost:8001/chat -H "Content-Type: application/json" -d '{
     "text": "Can you analyze the potential security risks of using public WiFi?"
   }'
   ```

   In the response, `meta.peers` lists the peers the agent consulted.

2. **Check Collaboration Logs**:

   ```bash
   docker compose logs agent1 | grep -E "Consulting|Delegation to|Assistance request"
   ```

### Testing Shared Memory

1. **Record a Chat Interaction**:

   ```bash
   curl -X POST http://localhost:8001/chat -H "Content-Type: application/json" -d '{"text": "Remember that the project deadline is May 15th"}'
   ```

2. **Verify the Interaction was Recorded**:

   ```bash
   curl http://localhost:8001/memory/agent_memory_agent1.agents.local
   ```

3. **Test Adding Custom Memory**:

   ```bash
   curl -X POST http://localhost:8001/memory -H "Content-Type: application/json" -d '{
     "key": "project_deadlines",
     "value": {"project_x": "May 15th", "project_y": "June 30th"},
     "owner": "user_interface"
   }'
   ```

4. **Test Referencing Stored Information**:

   ```bash
   curl -X POST http://localhost:8001/chat -H "Content-Type: application/json" -d '{"text": "What is the deadline for project X?"}'
   ```

   The agent should be able to check memory and find the stored deadline information.

5. **View Memory in Web UI**:

   Navigate to <http://localhost:5001> and click on the "Shared Memory" tab to view all stored memory entries.

### Monitoring and Debugging

To observe the agent discovery and memory operations in action:

1. **Watch the Logs**:

   ```bash
   # For collaboration
   docker compose logs -f agent1 | grep -E "peer|discover|gossip"
   
   # For memory operations
   docker compose logs -f agent1 | grep -E "memory|storing|record"
   ```

2. **Monitor Memory Status**:

   ```bash
   # Check memory entries periodically
   curl http://localhost:8001/memory | jq '.memory | keys'
   ```
