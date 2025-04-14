"""Service for interacting with LLMs."""

import logging
import os
import json
import anthropic
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with LLMs."""

    def __init__(self, api_key=None, config=None):
        """
        Initialize the LLM service.

        Args:
            api_key: API key for the LLM provider
            config: Configuration
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning("No API key provided for LLM service")

        self.config = config or {}
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = config.get("model", "claude-3-sonnet-20240229")

    async def generate_response(
        self, prompt: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            prompt: The prompt to send to the LLM
            context: Additional context like history or system messages

        Returns:
            The generated response
        """
        try:
            # Extract peer responses if available
            peer_responses = []
            if context and "peer_responses" in context:
                peer_responses = context["peer_responses"]

            # Build system prompt
            system_prompt = f"You are {self.config.get('name', 'an AI assistant')}."

            # If this is an assist request, adjust the system prompt
            if context and context.get("is_assist_request"):
                requestor_name = context.get("requestor_name", "another agent")
                system_prompt += f" You are helping {requestor_name} answer a question. Focus on providing information related to your specific capabilities: {', '.join(self.config.get('capabilities', []))}."
            else:
                system_prompt += (
                    f" You help users by providing informative, helpful responses."
                )

            # If we have peer responses, add them to the system prompt
            if peer_responses:
                system_prompt += "\n\nYou have received assistance from peer agents. Include relevant information from these peers in your response, citing them appropriately:"

                for i, peer_response in enumerate(peer_responses):
                    system_prompt += f"\n\nPeer {i+1} ({peer_response['peer_name']}): {peer_response['response']}"

            # Create the message for Anthropic
            messages = [{"role": "system", "content": system_prompt}]

            # Add chat history if available
            if context and "history" in context:
                for message in context["history"]:
                    if message["role"] in ["user", "assistant"]:
                        messages.append(
                            {"role": message["role"], "content": message["content"]}
                        )
            else:
                # If no history, just add the prompt as user message
                messages.append({"role": "user", "content": prompt})

            # Debug logging
            logger.debug(f"Sending to Anthropic: {json.dumps(messages, indent=2)}")

            # Call the API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=messages,
                temperature=0.7,
            )

            # Extract the text
            text = response.content[0].text
            logger.debug(f"Response from Anthropic: {text[:100]}...")

            return text
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return f"I'm sorry, but I encountered an error: {str(e)}"
