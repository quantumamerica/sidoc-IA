from __future__ import annotations

import logging

from clients.anthropic_client import AnthropicClient
from clients.base import BaseAIClient
from clients.gemini_client import GeminiClient
from config.settings import Settings

logger = logging.getLogger(__name__)


def build_judge_client(settings: Settings) -> BaseAIClient:
    """Cliente del juez IA (calidad de contenido y validacion de negocio).

    AI_JUDGE_PROVIDER=anthropic usa Claude; si falta ANTHROPIC_API_KEY se usa Gemini
    para que la corrida programada no quede sin juez.
    """
    if settings.ai_judge_provider == "gemini":
        return GeminiClient(settings)

    client = AnthropicClient(settings)
    if client.is_configured():
        return client

    logger.warning("AI_JUDGE_PROVIDER=anthropic pero ANTHROPIC_API_KEY no esta configurada; el juez usa Gemini.")
    return GeminiClient(settings)


def judge_label(client: BaseAIClient) -> str:
    return "Claude" if client.provider.value == "anthropic" else "Gemini"
