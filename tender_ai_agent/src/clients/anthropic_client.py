from __future__ import annotations

import logging
from typing import Any

from clients.base import BaseAIClient, ProviderResponse
from config.settings import Settings
from models.schemas import ProviderName

logger = logging.getLogger(__name__)

# Precios de lista (USD por millon de tokens: entrada, salida).
_PRICES_PER_MILLION = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
# Modelos que aceptan `fallbacks: "default"`: si el modelo declina la consulta,
# la API la reintenta con el modelo de respaldo recomendado dentro de la misma llamada.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_MAX_TOKENS = 16000


class AnthropicClient(BaseAIClient):
    provider_name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = ProviderName.ANTHROPIC
        self.model = settings.anthropic_model

    def is_configured(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    def run_agent(
        self,
        prompt: str,
        response_format: str = "json",
        stage: str | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        if not self.settings.anthropic_api_key:
            return self._error_response("ANTHROPIC_API_KEY no esta configurada.")

        def operation() -> ProviderResponse:
            try:
                import anthropic

                client = anthropic.Anthropic(
                    api_key=self.settings.anthropic_api_key,
                    timeout=float(self.settings.request_timeout_seconds),
                    max_retries=0,  # los reintentos los maneja BaseAIClient._with_retries
                )
                output_config: dict[str, Any] = {"effort": self.settings.anthropic_effort}
                if response_format == "json" and json_schema:
                    output_config["format"] = {"type": "json_schema", "schema": json_schema}

                request: dict[str, Any] = {
                    "model": self.model,
                    "max_tokens": _MAX_TOKENS,
                    "output_config": output_config,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if self.model in _FALLBACK_MODELS:
                    request["betas"] = [_FALLBACK_BETA]
                    request["fallbacks"] = "default"
                response = client.beta.messages.create(**request)

                if response.stop_reason == "refusal":
                    category = getattr(response.stop_details, "category", None) if response.stop_details else None
                    return self._error_response(f"Claude declino la consulta (categoria={category}).")
                if response.stop_reason == "max_tokens":
                    return self._error_response("Respuesta de Claude cortada por max_tokens.")

                content = "".join(block.text for block in response.content if block.type == "text").strip()
                if not content:
                    return self._error_response("Claude devolvio una respuesta vacia.")

                usage = response.usage
                return self._build_response(
                    content=content,
                    raw_response=response.to_dict(),
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    estimated_cost=self._estimate_cost(response.model, usage.input_tokens, usage.output_tokens),
                    metadata={
                        "api": "anthropic-messages",
                        "stage": stage,
                        "served_model": response.model,
                        "effort": self.settings.anthropic_effort,
                        "json_schema_enabled": "format" in output_config,
                    },
                )
            except Exception as exc:
                return self._error_response(exc)

        return self._with_retries(operation, stage=stage)

    @staticmethod
    def _estimate_cost(model: str | None, input_tokens: int | None, output_tokens: int | None) -> float | None:
        prices = _PRICES_PER_MILLION.get(model or "")
        if prices is None or (input_tokens is None and output_tokens is None):
            return None
        input_price, output_price = prices
        return ((input_tokens or 0) * input_price + (output_tokens or 0) * output_price) / 1_000_000
