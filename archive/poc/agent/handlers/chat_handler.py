"""Handler for chat interactions with the agent."""

import logging
import json
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class ChatHandler:
    """Handler for chat interactions with the agent."""

    def __init__(
        self, llm_service, collaborative_service=None, config=None, registry_client=None
    ):
        """
        Initialize the chat handler.

        Args:
            llm_service: Service for interacting with LLM
            collaborative_service: Service for collaborative answering
            config: Configuration
            registry_client: Client for interacting with the registry
        """
        self.llm_service = llm_service
        self.collaborative_service = collaborative_service
        self.config = config or {}
        self.registry_client = registry_client

        # Chat history (simple in-memory implementation)
        self.chat_history = {}

    def get_shared_memory(self) -> Dict:
        """Get all shared memory entries"""
        if not self.registry_client:
            logger.warning(
                "Cannot access shared memory: registry_client not initialized"
            )
            return {"memory": {}}
        return self.registry_client.get_shared_memory()

    def store_in_shared_memory(self, key: str, value: Any) -> Dict:
        """
        Store a value in shared memory

        Args:
            key: Memory key
            value: Value to store (must be JSON serializable)

        Returns:
            Response from registry
        """
        if not self.registry_client:
            logger.warning(
                "Cannot store in shared memory: registry_client not initialized"
            )
            return {"status": "error", "message": "registry_client not initialized"}

        try:
            # Validate that value is JSON serializable
            json_str = json.dumps(value)
            logger.debug(f"Serialized memory value (length: {len(json_str)})")

            agent_id = self.config.get("id", "unknown-agent")
            logger.info(f"Storing memory with key: {key}, owner: {agent_id}")

            result = self.registry_client.update_shared_memory(
                key, value, owner=agent_id
            )
            logger.info(f"Memory storage result: {result}")

            # Verify memory was stored
            if result.get("status") == "success":
                logger.info(f"Successfully stored memory with key: {key}")
            else:
                logger.warning(f"Possible issue storing memory: {result}")

            return result
        except TypeError as e:
            logger.error(f"Memory value is not JSON serializable: {e}")
            # Try to store a simplified version
            try:
                simplified_value = {
                    "error": "Original value not serializable",
                    "str_value": str(value),
                }
                return self.registry_client.update_shared_memory(
                    key, simplified_value, owner=agent_id
                )
            except Exception as e2:
                logger.error(f"Failed to store simplified memory value: {e2}")
                return {
                    "status": "error",
                    "message": f"Value not serializable: {str(e)}",
                }
        except Exception as e:
            logger.error(f"Unexpected error storing memory: {e}")
            return {"status": "error", "message": str(e)}

    def record_interaction_in_memory(
        self, user_message: str, response: str, session_id: str = "default"
    ) -> Optional[Dict]:
        """
        Record an interaction summary in shared memory

        Args:
            user_message: Message from the user
            response: Agent's response
            session_id: Chat session ID

        Returns:
            Response from the registry or None if error
        """
        agent_id = self.config.get("id", "unknown-agent")
        memory_key = f"agent_memory_{agent_id}"

        logger.info(f"Recording interaction for agent {agent_id} in key: {memory_key}")

        if not self.registry_client:
            logger.error("Cannot record interaction: registry_client not initialized")
            return None

        # Get existing memory or create new
        try:
            memory_result = self.get_shared_memory()
            logger.info(
                f"Retrieved memory, found {len(memory_result.get('memory', {}))} entries"
            )

            memory = memory_result.get("memory", {})
            logger.debug(f"Memory keys: {list(memory.keys())}")

            entry = memory.get(memory_key)
            logger.debug(f"Existing memory entry for {memory_key}: {entry is not None}")

            if entry is not None:
                agent_memory = entry.get("value", {})
                if not isinstance(agent_memory, dict):
                    logger.warning(
                        f"Memory value is not a dict, creating new. Type: {type(agent_memory)}"
                    )
                    agent_memory = {"interactions": []}
            else:
                logger.info(f"No existing memory for key {memory_key}, creating new")
                agent_memory = {"interactions": []}

            # Ensure interactions list exists
            if "interactions" not in agent_memory:
                logger.info("Adding empty interactions list to memory")
                agent_memory["interactions"] = []

        except Exception as e:
            logger.error(f"Error retrieving memory, creating new: {str(e)}")
            agent_memory = {"interactions": []}

        # Add the new interaction
        agent_memory["interactions"].append(
            {
                "user_message": user_message,
                "agent_response": response,
                "timestamp": time.time(),
                "session_id": session_id,
            }
        )

        # Keep only the last 10 interactions to prevent excessive growth
        if len(agent_memory["interactions"]) > 10:
            agent_memory["interactions"] = agent_memory["interactions"][-10:]

        # Store additional metadata
        agent_memory["last_updated"] = time.time()
        agent_memory["agent_name"] = self.config.get("name", "Unknown Agent")
        agent_memory["agent_id"] = agent_id

        # Save the updated memory
        try:
            return self.store_in_shared_memory(memory_key, agent_memory)
        except Exception as e:
            logger.error(f"Failed to store interaction in memory: {e}")
            return None

    async def handle_chat(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a chat request from a user or another agent.

        Args:
            request_data: The request data containing text/message

        Returns:
            Response with LLM-generated content
        """
        # Extract the user's message
        user_message = request_data.get("text") or request_data.get("message")
        session_id = request_data.get("session_id", "default")

        if not user_message:
            return {"status": "error", "error": "Missing text or message in request"}

        logger.info(f"Received chat message: {user_message[:50]}...")

        # Initialize chat history for this session if needed
        if session_id not in self.chat_history:
            self.chat_history[session_id] = []

        # Add user message to history
        self.chat_history[session_id].append(
            {"role": "user", "content": user_message, "timestamp": time.time()}
        )

        # Determine if we should use collaborative answering
        # For a simple heuristic, look for question marks or common question words
        question_indicators = [
            "?",
            "who",
            "what",
            "when",
            "where",
            "why",
            "how",
            "can you",
            "could you",
        ]
        is_question = any(
            indicator in user_message.lower() for indicator in question_indicators
        )

        peer_responses = []
        if is_question and self.collaborative_service:
            # Get assistance from peers
            logger.info("Question detected, getting assistance from peers")
            peer_responses = self.collaborative_service.get_assistance(user_message)
            logger.info(f"Received {len(peer_responses)} peer responses")

        # Prepare context
        context = {
            "history": self.chat_history[session_id],
            "peer_responses": peer_responses,
            "session_id": session_id,
        }

        # Call LLM for response
        try:
            # Construct the system prompt
            system_prompt = f"""You are {self.config.get('name', 'an AI assistant')}, an AI agent with the following capabilities: {', '.join(self.config.get('capabilities', []))}.

You help users by providing informative, helpful, and accurate responses. Your responses should be friendly, engaging, and tailored to the user's needs.
"""

            # Add peer response information if available
            if peer_responses:
                system_prompt += "\n\nYou have received assistance from peer agents. Include relevant information from these peers in your response, citing them appropriately."

                for i, peer_response in enumerate(peer_responses):
                    system_prompt += f"\n\nPeer {i+1} ({peer_response['peer_name']}): {peer_response['response']}"

            # Create the prompt with user message
            prompt = f"{system_prompt}\n\nUser: {user_message}\n\nAssistant:"

            response = await self.llm_service.generate_response(prompt, context)

            # Add assistant response to history
            self.chat_history[session_id].append(
                {"role": "assistant", "content": response, "timestamp": time.time()}
            )

            # Limit history length (keep last 10 messages)
            if len(self.chat_history[session_id]) > 10:
                self.chat_history[session_id] = self.chat_history[session_id][-10:]

            # Record the interaction in shared memory
            if self.registry_client:
                try:
                    self.record_interaction_in_memory(
                        user_message, response, session_id
                    )
                    logger.info(f"Recorded chat interaction in shared memory")
                except Exception as e:
                    logger.error(f"Failed to record chat in memory: {e}")

            result = {"response": response, "session_id": session_id}

            # Include metadata about peer assistance if available
            if peer_responses:
                result["meta"] = {
                    "collaborative": True,
                    "peer_count": len(peer_responses),
                    "peers": [pr["peer_name"] for pr in peer_responses],
                }

            return result
        except Exception as e:
            logger.error(f"Error handling chat: {e}")
            return {"status": "error", "error": f"Error generating response: {str(e)}"}
