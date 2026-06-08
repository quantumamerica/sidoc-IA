from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings
from clients.base import BaseAIClient, ProviderResponse
from models.schemas import ProviderName

logger = logging.getLogger(__name__)


class OpenAIClient(BaseAIClient):
    provider_name = "openai"
    web_search_tool_type = "web_search"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = ProviderName.OPENAI
        self.model = settings.openai_model

    def is_configured(self) -> bool:
        return bool(self.settings.openai_api_key)

    def run_agent(
        self,
        prompt: str,
        response_format: str = "json",
        stage: str | None = None,
    ) -> ProviderResponse:
        if not self.settings.openai_api_key:
            return self._error_response("OPENAI_API_KEY no esta configurada.")

        def operation() -> ProviderResponse:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=self.settings.openai_api_key, timeout=self.settings.request_timeout_seconds)
                kwargs: dict[str, Any] = {
                    "model": self.settings.openai_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                }
                if response_format == "json":
                    kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content if response.choices else None
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
                output_tokens = getattr(usage, "completion_tokens", None) if usage else None
                raw_response = response.model_dump(mode="json") if hasattr(response, "model_dump") else None

                return self._build_response(
                    content=content,
                    raw_response=raw_response,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost=None,
                )
            except Exception as exc:
                return self._error_response(exc)

        return self._with_retries(operation, stage=stage)

    def run_discovery(self, prompt: str) -> ProviderResponse:
        if not self.settings.openai_api_key:
            return self._error_response("OPENAI_API_KEY no esta configurada.")

        def operation() -> ProviderResponse:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=self.settings.openai_api_key, timeout=self.settings.request_timeout_seconds)
                logger.info(
                    "OpenAI discovery usando Responses API con web_search habilitado modelo=%s",
                    self.settings.openai_model,
                )
                response = client.responses.create(
                    model=self.settings.openai_model,
                    tools=[{"type": self.web_search_tool_type}],
                    input=prompt,
                    temperature=0.1,
                )
                content = getattr(response, "output_text", None)
                if not content:
                    return self._error_response("OpenAI Responses API devolvio una respuesta vacia para discovery.")

                usage = getattr(response, "usage", None)
                raw_response = response.model_dump(mode="json") if hasattr(response, "model_dump") else None

                return self._build_response(
                    content=content,
                    raw_response=raw_response,
                    input_tokens=self._usage_value(usage, "input_tokens", "prompt_tokens"),
                    output_tokens=self._usage_value(usage, "output_tokens", "completion_tokens"),
                    estimated_cost=None,
                    metadata={
                        "api": "responses",
                        "tool": self.web_search_tool_type,
                        "web_search_enabled": True,
                        "stage": "discovery",
                    },
                )
            except Exception as exc:
                return self._error_response(exc)

        return self._with_retries(operation, stage="discovery")

    @staticmethod
    def _usage_value(usage: Any, *names: str) -> int | None:
        if usage is None:
            return None
        for name in names:
            value = getattr(usage, name, None)
            if value is not None:
                return value
        if isinstance(usage, dict):
            for name in names:
                value = usage.get(name)
                if value is not None:
                    return value
        return None
