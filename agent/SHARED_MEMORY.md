# Shared Memory Functionality in Agent Name Server

This document explains how the rudimentary (in-memory) shared memory feature works in the Agent Name Server system.

## Overview

The shared memory functionality allows agents to store and retrieve data through a central registry. This enables:

1. Persistent information across agent restarts
2. Information sharing between different agents
3. Storing chat history and interactions for future reference
4. Building collective knowledge across the agent network

## Architecture

The shared memory system follows a simple client-server model:

1. The **registry server** manages a central in-memory store
2. **Agents** use the registry client to read from and write to this store
3. Memory entries are stored as key-value pairs with metadata

```
                ┌─────────────┐
                │   Registry  │
                │   Server    │
                └─────┬───────┘
                      │
                      │ HTTP API
                      │
        ┌─────────────┼─────────────┐
        │             │             │
┌───────▼─────┐ ┌─────▼───────┐ ┌───▼───────────┐
│   Agent 1   │ │   Agent 2   │ │    Agent 3    │
└─────────────┘ └─────────────┘ └───────────────┘
```

## Implementation Details

### Registry Server

The registry server (`registry/app.py`) implements two key endpoints:

1. **GET /shared-memory** - Returns all memory entries
2. **POST /shared-memory** - Adds or updates a memory entry

Memory is stored in a simple dictionary structure:

```python
shared_memory = {
    "key1": {
        "value": { ... },  # Any JSON-serializable value
        "timestamp": 1713038401.345,
        "owner": "agent1.agents.local"
    },
    "key2": { ... }
}
```

### Agent Implementation

Agents access shared memory through the `RegistryClient` which has been extended with:

1. **get_shared_memory()** - Retrieves all memory entries
2. **update_shared_memory(key, value, owner)** - Creates or updates a memory entry

The `Agent` class has methods for high-level memory operations:

1. **store_in_shared_memory(key, value)** - Stores a value in memory
2. **record_interaction_in_memory(user_message, response, session_id)** - Records chat interactions

### Chat Handler

The `ChatHandler` class also implements shared memory functionality for handler-based agent architecture:

1. Accepts a registry_client in its constructor
2. Implements memory access and storage methods
3. Automatically records chat interactions in memory

## Memory Structure

### Agent Memory Format

Each agent creates a memory entry with its agent ID as part of the key:

```bash
agent_memory_{agent_id}
```

The memory structure contains:

```json
{
  "interactions": [
    {
      "user_message": "Hello, how are you?",
      "agent_response": "I'm doing well, thank you for asking!",
      "timestamp": 1713038401.345,
      "session_id": "default"
    },
    ...
  ],
  "last_updated": 1713038401.345,
  "agent_name": "Agent Analyzer",
  "agent_id": "agent5.agents.local"
}
```

## Usage Examples

### Basic Memory Operations

```python
# Get all memory entries
memory = registry_client.get_shared_memory()

# Store a value in memory
registry_client.update_shared_memory(
    key="agent_notes",
    value={"important": "Remember this information"},
    owner="agent1.agents.local"
)
```

### Recording Chat Interactions

Chat interactions are automatically recorded when using the Agent class's `handle_chat` method or the ChatHandler's `handle_chat` method. The memory is stored using the agent's ID as part of the key.

### Custom Memory Usage

Agents can create custom memory entries for any purpose:

```python
# Store analysis results
agent.store_in_shared_memory(
    "analysis_results", 
    {
        "sentiment": "positive",
        "topics": ["weather", "greetings"],
        "timestamp": time.time()
    }
)
```

## Testing

A test script is provided at `agent/test_memory.py` to verify the shared memory functionality:

1. Creates a test memory entry
2. Retrieves and verifies the entry exists
3. Updates the entry
4. Tests the chat memory recording

Run the test with:

```bash
cd agent
python test_memory.py
```

## Web UI Access

The shared memory can be viewed and edited through the registry's web interface at:

<http://localhost:5001/>

Navigate to the "Shared Memory" tab to view all memory entries, their values, owners, and timestamps.
