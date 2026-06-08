from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from models.schemas import ProviderName

logger = logging.getLogger(__name__)


class ProviderResponse(BaseModel):
    provider: ProviderName
    model: str
    content: str | None = None
    parsed_json: Any | None = None
    raw_response: dict[str, Any] | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class BaseAIClient(ABC):
    provider: ProviderName
    model: str
    max_retries: int = 2
    retry_delay_seconds: float = 1.5

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def run_agent(
        self,
        prompt: str,
        response_format: str = "json",
        stage: str | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError

    def complete(self, messages: list[dict[str, str]]) -> str:
        prompt = self.messages_to_prompt(messages)
        response = self.run_agent(prompt)
        if response.error:
            raise RuntimeError(response.error)
        return response.content or ""

    def run_discovery(self, prompt: str) -> ProviderResponse:
        return self.run_agent(prompt, response_format="json", stage="discovery")

    def _with_retries(self, operation: Callable[[], ProviderResponse], *, stage: str | None = None) -> ProviderResponse:
        started = time.perf_counter()
        last_response: ProviderResponse | None = None

        for attempt in range(1, self.max_retries + 2):
            response = operation()
            last_response = response
            if response.ok:
                self._log_call(response, started=started, stage=stage)
                return response
            if attempt <= self.max_retries:
                logger.warning(
                    "Error en proveedor=%s modelo=%s etapa=%s intento=%s: %s",
                    self.provider.value,
                    self.model,
                    stage,
                    attempt,
                    response.error,
                )
                time.sleep(self.retry_delay_seconds * attempt)

        assert last_response is not None
        self._log_call(last_response, started=started, stage=stage)
        return last_response

    def _build_response(
        self,
        *,
        content: str | None,
        raw_response: dict[str, Any] | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost: float | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            provider=self.provider,
            model=self.model,
            content=content,
            parsed_json=parse_json_content(content),
            raw_response=raw_response,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            metadata=metadata or {},
            error=error,
        )

    def _error_response(self, error: Exception | str) -> ProviderResponse:
        return self._build_response(content=None, error=str(error))

    def _log_call(self, response: ProviderResponse, *, started: float, stage: str | None = None) -> None:
        duration = time.perf_counter() - started
        if response.error:
            logger.error(
                "Llamada IA fallo proveedor=%s modelo=%s etapa=%s duracion=%.2fs error=%s",
                response.provider.value,
                response.model,
                stage,
                duration,
                response.error,
            )
            return

        logger.info(
            "Llamada IA ok proveedor=%s modelo=%s etapa=%s input_tokens=%s output_tokens=%s duracion=%.2fs metadata=%s",
            response.provider.value,
            response.model,
            stage,
            response.input_tokens,
            response.output_tokens,
            duration,
            response.metadata,
        )

    @staticmethod
    def messages_to_prompt(messages: list[dict[str, str]]) -> str:
        return "\n\n".join(f"{message.get('role', 'user').upper()}:\n{message.get('content', '')}" for message in messages)


def parse_json_content(content: str | None) -> Any | None:
    if not content:
        return None

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
