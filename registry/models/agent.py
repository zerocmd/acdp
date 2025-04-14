"""Agent model definition for the registry."""

from datetime import datetime
import json


class Agent:
    """Model representing an agent in the registry."""

    def __init__(self, data):
        """Initialize from a data dictionary."""
        self.id = data.get("id")
        self.name = data.get("name")
        self.description = data.get("description", "")
        self.capabilities = data.get("capabilities", [])
        self.interfaces = data.get("interfaces", {})
        self.version = data.get("version", "1.0.0")
        self.protocols = data.get("protocols", [])
        self.model_info = data.get("model_info", {})
        self.owner = data.get("owner", "")
        self.endpoints = data.get("endpoints", {})
        self.last_update = data.get("last_update", datetime.now().timestamp())

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "interfaces": self.interfaces,
            "version": self.version,
            "protocols": self.protocols,
            "model_info": self.model_info,
            "owner": self.owner,
            "endpoints": self.endpoints,
            "last_update": self.last_update,
        }

    def validate(self):
        """Validate the agent data."""
        if not self.id:
            raise ValueError("Agent ID is required")
        if not self.name:
            raise ValueError("Agent name is required")
        if not self.capabilities:
            raise ValueError("Agent must have at least one capability")
        if not self.interfaces:
            raise ValueError("Agent must have at least one interface")

        return True

    @classmethod
    def from_json(cls, json_str):
        """Create an agent from JSON string."""
        try:
            data = json.loads(json_str)
            return cls(data)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON data")
