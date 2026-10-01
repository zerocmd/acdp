"""Model provider selection for Strands agents."""

from typing import Any, Callable, Dict

from strands.models import Model

ModelFactory = Callable[[], Model]


def build_model(model_config: Dict[str, Any]) -> Model:
    """Model provider selected by MODEL_PROVIDER / MODEL_ID."""
    provider = model_config.get("provider", "anthropic")
    model_id = model_config.get("model_id")
    max_tokens = int(model_config.get("max_tokens", 16000))

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        # The Anthropic client reads ANTHROPIC_API_KEY from the environment.
        return AnthropicModel(
            model_id=model_id or "claude-sonnet-5-5", max_tokens=max_tokens
        )

    if provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        if not model_id:
            raise ValueError("MODEL_ID is required when MODEL_PROVIDER=bedrock")
        return BedrockModel(
            model_id=model_id,
            max_tokens=max_tokens,
            region_name=model_config.get("region"),
        )

    raise ValueError(
        f"Unsupported MODEL_PROVIDER: {provider!r} (use 'anthropic' or 'bedrock')"
    )
