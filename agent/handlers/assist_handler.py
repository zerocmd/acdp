"""Handler for assistance requests from other agents."""

import logging
import json
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AssistHandler:
    """Handler for assistance requests from other agents."""

    def __init__(self, llm_service, config=None):
        """
        Initialize the assist handler.

        Args:
            llm_service: Service for interacting with LLM
            config: Configuration
        """
        self.llm_service = llm_service
        self.config = config or {}

    async def handle_assist(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle an assistance request from another agent.

        Args:
            request_data: The request data including question

        Returns:
            Response with assistance
        """
        question = request_data.get("question")
        requestor_id = request_data.get("requestor_id", "unknown-agent")
        requestor_name = request_data.get("requestor_name", "Unknown Agent")

        if not question:
            return {"status": "error", "error": "Missing question in request"}

        logger.info(
            f"Received assistance request from {requestor_name} ({requestor_id}): {question}"
        )

        # Prepare context for LLM
        context = {
            "requestor_id": requestor_id,
            "requestor_name": requestor_name,
            "agent_id": self.config.get("id", "unknown"),
            "agent_name": self.config.get("name", "Unknown Agent"),
            "agent_capabilities": self.config.get("capabilities", []),
            "is_assist_request": True,
        }

        # Call LLM for assistance
        try:
            # Create a special prompt for assistance requests
            prompt = f"""You are {self.config.get('name', 'an AI assistant')}, helping another agent named {requestor_name}.

{requestor_name} has asked for your assistance with the following question:

"{question}"

Provide a helpful, concise response based on your knowledge and capabilities. 
Your response will be incorporated into the final answer by {requestor_name}.
Focus on providing information related to your specific capabilities: {', '.join(self.config.get('capabilities', []))}.
"""

            response = await self.llm_service.generate_response(prompt, context)

            return {
                "status": "success",
                "response": response,
                "agent_id": self.config.get("id"),
                "agent_name": self.config.get("name"),
            }
        except Exception as e:
            logger.error(f"Error generating assistance response: {e}")
            return {"status": "error", "error": f"Error generating response: {str(e)}"}
