from app.ai.base import AIProvider
from app.ai.mock import MockAIProvider
from app.ai.openai_provider import OpenAIProvider
from app.core.config import get_settings


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider.lower() == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    return MockAIProvider()
