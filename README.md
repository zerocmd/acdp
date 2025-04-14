# Agent Communication, Discovery & Memory Protocol PoC

This proof of concept implements a basic version of the Agent Communication & Discovery Protocol, allowing AI agents to register, discover, communicate with each other, and share memory. This implementation is only provided as an example to visualize the approaches outlined in the document. It's not intended to be comprehensive and does not cover any of the security related options outlined.

## Components

- **DNS Server (BIND9)**: Provides DNS-based discovery with SRV and TXT records
- **Central Registry**: Flask-based service for agent registration, discovery, and shared memory
- **Agents**: Multiple Anthropic Sonnet-powered agents that register, discover each other, and collaborate

## Setup

You will require a BIND server as a Docker image: [BIND 9](https://hub.docker.com/r/ubuntu/bind9/)

1. Clone this repository
2. Set your Anthropic API key in an environment variable:

   ```bash
   export ANTHROPIC_API_KEY=your_api_key_here
   ```

3. Install dependencies (if not using Docker):

   ```bash
   pip install -r requirements.txt
   ```

4. Start the services:

   ```bash
   docker-compose up -d
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
Agent 3: <http://localhost:8003/chat>

Example API call:

```bash
curl -X POST http://localhost:8001/chat -H "Content-Type: application/json" -d '{"text": "Hello, can you help me with something?"}'
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

Agents are defined in `docker-compose.yml`

```yaml
  # Add the new agent with correct context
  agent5:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8005:8000"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - AGENT_ID=agent5.agents.local
      - AGENT_NAME=Agent Analyzer
      - AGENT_DESCRIPTION=AI assistant specializing in security analysis and threat detection
      - AGENT_PORT=8000
      - AGENT_HOSTNAME=agent5
      - REGISTRY_URL=http://registry:5000
      - DNS_API_URL=http://bind:8053
      - AGENT_CAPABILITIES=security,threat_detection,attack_patterns
    networks:
      - agent_network
```

## Architecture

This implementation follows the Agent Communication & Discovery Protocol specification:

1. Agents register with both DNS (via SRV/TXT records) and a central registry
2. Agents discover each other through the registry and maintain peer lists
3. Agents communicate directly with each other via REST APIs
4. Agents can collaborate by requesting assistance from peers with relevant capabilities
5. Agents can store and retrieve information using the shared memory system
6. Heartbeats maintain registry consistency

### Shared Memory Architecture

The shared memory system follows a simple client-server model:

1. The **registry server** manages a central in-memory store
2. **Agents** use the registry client to read from and write to this store
3. Memory entries are stored as key-value pairs with metadata (owner, timestamp)
4. Agents automatically record chat interactions in memory for future reference

### Agent Collaboration

Agents can collaborate to solve problems through:

1. **Capability-based Discovery**: Agents find peers with specific abilities
2. **Assistance Requests**: Agents can ask peers for help on specific questions
3. **Knowledge Sharing**: Agents can reference shared memory for context
4. **Collective Response**: Agents combine peer responses with their own knowledge

When an agent receives a question that might benefit from collaboration:

1. It identifies peers with relevant capabilities
2. It sends assistance requests to those peers
3. It collects responses from peers
4. It crafts a comprehensive response that incorporates peer knowledge
5. It records the interaction in shared memory

## Extensions

This proof of concept can be extended with:

- Authentication and security measures
- Additional agent capabilities
- Peer-to-peer task delegation
- DNSSEC for DNS security
- HTTPS for transport layer security
- Persistent storage for agent and shared memory

## Testing the Implementation

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

   In the response, observe if the agent gathered assistance from peers with security expertise.

2. **Check Collaboration Logs**:

   ```bash
   docker compose logs agent1 | grep -E "Question detected|peers for collaboration|Querying peer|peer responses|Received response from peer|Received assistance request from"
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

## Folder Structure

```text
.
├── README.md
├── agent
│   ├── DockerFile
│   ├── agent.py
│   ├── config.py
│   ├── SHARED_MEMORY.md
│   ├── discovery
│   │   ├── __init__.py
│   │   ├── discovery_service.py
│   │   ├── dns_resolver.py
│   │   └── registry_client.py
│   ├── handlers
│   │   ├── __init__.py
│   │   ├── assist_handler.py
│   │   └── chat_handler.py
│   ├── peers
│   │   ├── __init__.py
│   │   ├── gossip.py
│   │   └── peer_manager.py
│   ├── requirements.txt
│   ├── services
│   │   ├── __init__.py
│   │   ├── collaborative_service.py
│   │   └── llm_service.py
│   ├── test_assist_endpoint.py
│   ├── test_collab_timeout.py
│   ├── test_collaboration.py
│   ├── test_collaboration_2.py
│   ├── test_collaboration_3.py
│   ├── test_memory.py
│   └── utils
│       ├── __init__.py
│       ├── dns_utils.py
│       └── registry_client.old
├── dns
│   ├── DockerFile
│   ├── named.conf
│   ├── scripts
│   │   ├── dns_api.py
│   │   └── update_zone.sh
│   └── zones
│       ├── db.127.0.0
│       └── db.agents.local
├── docker-compose.yml
└── registry
    ├── DockerFile
    ├── app.py
    ├── models
    │   └── agent.py
    ├── requirements.txt
    ├── services
    │   ├── __init__.py
    │   └── search.py
    ├── static
    │   ├── css
    │   │   └── dracula.css
    │   └── js
    │       └── main.js
    └── templates
        └── index.html
```
