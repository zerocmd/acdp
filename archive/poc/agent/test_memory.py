#!/usr/bin/env python3
"""
Test script for agent shared memory functionality
"""

import os
import json
import time
import requests
import logging
from discovery.registry_client import RegistryClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define agent configurations
AGENT_ID = os.environ.get("AGENT_ID", "test-agent.agents.local")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:5001")


def test_shared_memory():
    """Test shared memory functionality"""
    # Initialize registry client
    registry = RegistryClient(REGISTRY_URL)

    # 1. Create a memory entry
    key = f"test_memory_{int(time.time())}"
    value = {
        "test": True,
        "timestamp": time.time(),
        "data": {"message": "This is a test memory entry", "count": 1},
    }

    logger.info(f"Creating memory entry with key: {key}")
    result = registry.update_shared_memory(key, value, owner=AGENT_ID)
    logger.info(f"Create memory result: {result}")

    # 2. Get all memory entries
    logger.info("Getting all memory entries")
    memory = registry.get_shared_memory()
    logger.info(f"Found {len(memory.get('memory', {}))} memory entries")
    logger.info(f"Memory response structure: {json.dumps(memory, indent=2)}")

    # 3. Verify our test entry is present
    if key in memory.get("memory", {}):
        logger.info(f"Found our test entry with key: {key}")
    else:
        logger.error(
            f"Test entry not found! Memory keys: {list(memory.get('memory', {}).keys())}"
        )

    # 4. Update the memory entry
    value["data"]["count"] = 2
    logger.info(f"Updating memory entry with key: {key}")
    result = registry.update_shared_memory(key, value, owner=AGENT_ID)
    logger.info(f"Update memory result: {result}")

    # 5. Get the updated entry
    memory = registry.get_shared_memory()
    updated_entry = memory.get("memory", {}).get(key, {})
    if updated_entry:
        updated_value = updated_entry.get("value", {})
        logger.info(
            f"Updated count value: {updated_value.get('data', {}).get('count')}"
        )
        if updated_value.get("data", {}).get("count") == 2:
            logger.info("Memory update successful!")
        else:
            logger.error("Memory update failed, count not updated")

    # 6. Test agent chat memory recording
    # Note: This requires the agent to be running
    try:
        logger.info("Testing chat memory recording by sending a message to agent")
        test_message = "Hello, this is a test message to verify memory recording."

        response = requests.post(
            f"http://localhost:8000/chat",  # Assumes default agent port
            json={"text": test_message},
            timeout=10,
        )

        if response.status_code == 200:
            logger.info("Chat message sent successfully")
            # Give some time for memory to be recorded
            time.sleep(2)

            # Check if agent recorded the chat in memory
            memory = registry.get_shared_memory()
            agent_memory_key = f"agent_memory_{AGENT_ID}"

            if agent_memory_key in memory.get("memory", {}):
                logger.info(f"Found agent memory entry")
                agent_memory = (
                    memory.get("memory", {}).get(agent_memory_key, {}).get("value", {})
                )
                interactions = agent_memory.get("interactions", [])

                if interactions:
                    logger.info(f"Agent has {len(interactions)} recorded interactions")
                    latest = interactions[-1]
                    if latest.get("user_message") == test_message:
                        logger.info("Success! Found our test message in agent memory.")
                    else:
                        logger.info("Latest message doesn't match our test message.")
                else:
                    logger.warning("No interactions found in agent memory")
            else:
                logger.warning(f"No agent memory found with key: {agent_memory_key}")
        else:
            logger.error(
                f"Failed to send chat message: {response.status_code} - {response.text}"
            )
    except Exception as e:
        logger.error(f"Error testing chat memory recording: {e}")

    logger.info("Memory test completed")


if __name__ == "__main__":
    test_shared_memory()
