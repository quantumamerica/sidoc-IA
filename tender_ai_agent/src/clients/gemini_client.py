from __future__ import annotations

import logging
from typing import Any

from clients.base import BaseAIClient, ProviderResponse
from config.settings import Settings
from models.schemas import ProviderName

logger = logging.getLogger(__name__)

# Precios aproximados (USD por token) para gemini-2.5-flash-lite.
_INPUT_COST_PER_TOKEN = 0.10 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 0.40 / 1_000_000


class GeminiClient(BaseAIClient):
    provider_name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = ProviderName.GEMINI
        self.model = settings.gemini_model

    def is_configured(self) -> bool:
        return bool(self.settings.google_api_key)

    def run_agent(
        self,
        prompt: str,
        response_format: str = "json",
        stage: str | None = None,
    ) -> ProviderResponse:
        if not self.settings.google_api_key:
            return self._error_response("GOOGLE_API_KEY no esta configurada.")

        def operation() -> ProviderResponse:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.settings.google_api_key)
                config = types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json" if response_format == "json" else "text/plain",
                )
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                content = getattr(response, "text", None)
                if not content:
                    return self._error_response("Gemini devolvio una respuesta vacia.")

                usage = getattr(response, "usage_metadata", None)
                input_tokens = getattr(usage, "prompt_token_count", None) if usage else None
                output_tokens = getattr(usage, "candidates_token_count", None) if usage else None

                return self._build_response(
                    content=content,
                    raw_response=self._raw_response(response),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost=self._estimate_cost(input_tokens, output_tokens),
                    metadata={"api": "google-genai", "stage": stage},
                )
            except Exception as exc:
                return self._error_response(exc)

        return self._with_retries(operation, stage=stage)

    @staticmethod
    def _raw_response(response: Any) -> dict[str, Any] | None:
        for attribute in ("model_dump", "to_json_dict"):
            method = getattr(response, attribute, None)
            if callable(method):
                try:
                    return method(mode="json") if attribute == "model_dump" else method()
                except TypeError:
                    try:
                        return method()
                    except Exception:
                        return None
                except Exception:
                    return None
        return None

    @staticmethod
    def _estimate_cost(input_tokens: int | None, output_tokens: int | None) -> float | None:
        if input_tokens is None and output_tokens is None:
            return None
        return (input_tokens or 0) * _INPUT_COST_PER_TOKEN + (output_tokens or 0) * _OUTPUT_COST_PER_TOKEN
