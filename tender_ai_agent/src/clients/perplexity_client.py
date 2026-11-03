from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from config.settings import Settings
from clients.base import BaseAIClient, ProviderResponse
from models.schemas import ProviderName, SourceConfig

logger = logging.getLogger(__name__)


class PerplexityClient(BaseAIClient):
    provider_name = "perplexity"
    endpoint = "https://api.perplexity.ai/chat/completions"
    agent_endpoint = "https://api.perplexity.ai/v1/agent"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = ProviderName.PERPLEXITY
        self.model = settings.perplexity_model
        # Si la Agent API rechaza el pedido (4xx), el resto de la corrida usa Sonar directo.
        self._agent_rejected = False

    def is_configured(self) -> bool:
        return bool(self.settings.perplexity_api_key)

    def run_agent(
        self,
        prompt: str,
        response_format: str = "json",
        stage: str | None = None,
        search_domain_filter: list[str] | None = None,
        search_recency_filter: str | None = None,
        web_search_options: dict[str, Any] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        if not self.settings.perplexity_api_key:
            return self._error_response("PERPLEXITY_API_KEY no esta configurada.")

        def operation() -> ProviderResponse:
            try:
                import requests

                payload: dict[str, Any] = {
                    "model": self.settings.perplexity_model,
                    "messages": [{"role": "user", "content": self._prompt_with_json_instruction(prompt, response_format)}],
                    "temperature": 0.1,
                }
                if search_domain_filter:
                    payload["search_domain_filter"] = search_domain_filter[:20]
                if search_recency_filter:
                    payload["search_recency_filter"] = search_recency_filter
                if web_search_options:
                    payload["web_search_options"] = web_search_options
                if json_schema:
                    payload["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "discovery_items",
                            "schema": json_schema,
                            "strict": True,
                        },
                    }
                headers = {
                    "Authorization": f"Bearer {self.settings.perplexity_api_key}",
                    "Content-Type": "application/json",
                }

                response = requests.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.settings.request_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                usage = data.get("usage") or {}
                cost = usage.get("cost") or {}

                return self._build_response(
                    content=content,
                    raw_response=data,
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    estimated_cost=cost.get("total_cost"),
                    metadata={
                        "api": "chat_completions",
                        "endpoint": self.endpoint,
                        "stage": stage,
                        "search_domain_filter": search_domain_filter or [],
                        "search_recency_filter": search_recency_filter,
                        "web_search_options": web_search_options or {},
                        "json_schema_enabled": bool(json_schema),
                    },
                )
            except Exception as exc:
                return self._error_response(exc)

        return self._with_retries(operation, stage=stage)

    def run_discovery(self, prompt: str, *, source: SourceConfig | None = None) -> ProviderResponse:
        search_domain_filter = self._search_domain_filter(source)
        if self.settings.perplexity_discovery_api == "agent" and not self._agent_rejected:
            response = self._run_agent_discovery(prompt, search_domain_filter)
            if response.ok:
                return response
            logger.warning(
                "Perplexity Agent API fallo (%s); se repite la busqueda por el endpoint Sonar.",
                response.error,
            )
        logger.info(
            "Perplexity discovery usando Sonar modelo=%s endpoint=%s domains=%s",
            self.settings.perplexity_model,
            self.endpoint,
            search_domain_filter,
        )
        return self.run_agent(
            prompt,
            response_format="json",
            stage="discovery",
            search_domain_filter=search_domain_filter,
            search_recency_filter="year",
            web_search_options={"search_context_size": "medium", "search_type": "pro"},
            json_schema=self._discovery_json_schema(),
        )

    def _run_agent_discovery(self, prompt: str, search_domain_filter: list[str]) -> ProviderResponse:
        """Busqueda por la Agent API de Perplexity (/v1/agent).

        Desde el 27-sep-2026 el endpoint Sonar se atiende como Agent API con esfuerzo "fast": un
        solo paso y una sola busqueda. La Pro Search que usabamos equivale a esfuerzo "low"
        (hasta 5 pasos con busqueda web y lectura de paginas).
        """
        if not self.settings.perplexity_api_key:
            return self._error_response("PERPLEXITY_API_KEY no esta configurada.")
        effort = self.settings.perplexity_agent_effort
        logger.info(
            "Perplexity discovery usando Agent API esfuerzo=%s endpoint=%s domains=%s",
            effort,
            self.agent_endpoint,
            search_domain_filter,
        )
        filters: dict[str, Any] = {"search_recency_filter": "year"}
        if search_domain_filter:
            filters["search_domain_filter"] = search_domain_filter[:20]
        payload: dict[str, Any] = {
            "effort": effort,
            "input": self._prompt_with_json_instruction(prompt, "json"),
            "tools": [
                {
                    "type": "web_search",
                    "filters": filters,
                    "max_results": self.settings.perplexity_agent_max_results,
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "discovery_items",
                    "schema": self._discovery_json_schema(),
                    "strict": True,
                },
            },
        }

        def operation() -> ProviderResponse:
            try:
                import requests

                response = requests.post(
                    self.agent_endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.settings.perplexity_api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=max(self.settings.request_timeout_seconds, self.settings.perplexity_agent_timeout_seconds),
                )
                if response.status_code >= 400:
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        self._agent_rejected = True
                    return self._error_response(f"HTTP {response.status_code}: {response.text[:500]}")
                data = response.json()
            except Exception as exc:
                return self._error_response(exc)

            content = self._agent_output_text(data)
            search_results = self._agent_search_results(data)
            raw = dict(data)
            # Mismo formato que Sonar para que la segunda lectura y los reportes sigan funcionando.
            raw["search_results"] = search_results
            raw["citations"] = [r["url"] for r in search_results]
            usage = data.get("usage") or {}
            cost = usage.get("cost")
            if isinstance(cost, dict):
                cost = cost.get("total_cost")
            return self._build_response(
                content=content,
                raw_response=raw,
                input_tokens=usage.get("input_tokens", usage.get("prompt_tokens")),
                output_tokens=usage.get("output_tokens", usage.get("completion_tokens")),
                estimated_cost=cost if isinstance(cost, (int, float)) else None,
                metadata={
                    "api": "agent",
                    "endpoint": self.agent_endpoint,
                    "effort": effort,
                    "stage": "discovery",
                    "search_domain_filter": search_domain_filter,
                    "search_recency_filter": "year",
                    "json_schema_enabled": True,
                },
            )

        def operation_without_retry_on_rejection() -> ProviderResponse:
            if self._agent_rejected:
                return self._error_response("Agent API rechazo el pedido.")
            return operation()

        return self._with_retries(operation_without_retry_on_rejection, stage="discovery")

    @staticmethod
    def _agent_output_text(data: dict[str, Any]) -> str | None:
        text = data.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        parts: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
                continue
            for block in content or []:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "".join(parts) or None

    @staticmethod
    def _agent_search_results(data: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "search_results":
                continue
            for result in item.get("results") or []:
                if not isinstance(result, dict):
                    continue
                url = result.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(
                    {
                        "title": result.get("title"),
                        "url": url,
                        "snippet": result.get("snippet") or result.get("content"),
                        "date": result.get("date"),
                        "last_updated": result.get("last_updated"),
                    }
                )
        return results

    @staticmethod
    def _prompt_with_json_instruction(prompt: str, response_format: str) -> str:
        if response_format != "json":
            return prompt
        return (
            f"{prompt}\n\n"
            "Instruccion obligatoria de formato: responde solamente JSON valido y estricto, "
            "sin Markdown, sin texto introductorio y sin comentarios."
        )

    @staticmethod
    def _search_domain_filter(source: SourceConfig | None) -> list[str]:
        if source is None:
            return []
        domains = list(dict.fromkeys(source.search_domains))
        if not domains and source.url:
            parsed = urlparse(source.url)
            domain = parsed.netloc or parsed.path
            if domain:
                domains.append(domain)
        return domains

    @staticmethod
    def _discovery_json_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source_id": {"type": ["string", "null"]},
                            "source_name": {"type": ["string", "null"]},
                            "source_url": {"type": ["string", "null"]},
                            "raw_title": {"type": ["string", "null"]},
                            "normalized_title": {"type": ["string", "null"]},
                            "official_url": {"type": ["string", "null"]},
                            "all_urls": {"type": "array", "items": {"type": "string"}},
                            "contracting_authority": {"type": ["string", "null"]},
                            "country": {"type": ["string", "null"]},
                            "geographic_scope": {"type": ["string", "null"]},
                            "process_type": {"type": ["string", "null"]},
                            "consultant_type": {"type": ["string", "null"]},
                            "deadline_raw": {"type": ["string", "null"]},
                            "deadline_normalized": {"type": ["string", "null"]},
                            "publication_date_raw": {"type": ["string", "null"]},
                            "publication_date_normalized": {"type": ["string", "null"]},
                            "modification_date_raw": {"type": ["string", "null"]},
                            "modification_date_normalized": {"type": ["string", "null"]},
                            "description_raw": {"type": ["string", "null"]},
                            "description_summary": {"type": ["string", "null"]},
                            "language": {"type": ["string", "null"]},
                            "topic": {"type": ["string", "null"]},
                            "category": {"type": ["string", "null"]},
                            "matched_keywords": {"type": "array", "items": {"type": "string"}},
                            "matched_keywords_count": {"type": ["integer", "null"]},
                            "evidence_text": {"type": ["string", "null"]},
                            "evidence_urls": {"type": "array", "items": {"type": "string"}},
                            "requires_human_review": {"type": "boolean"},
                            "audit_notes": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "source_id",
                            "source_name",
                            "source_url",
                            "raw_title",
                            "normalized_title",
                            "official_url",
                            "all_urls",
                            "contracting_authority",
                            "country",
                            "geographic_scope",
                            "process_type",
                            "consultant_type",
                            "deadline_raw",
                            "deadline_normalized",
                            "publication_date_raw",
                            "publication_date_normalized",
                            "modification_date_raw",
                            "modification_date_normalized",
                            "description_raw",
                            "description_summary",
                            "language",
                            "topic",
                            "category",
                            "matched_keywords",
                            "matched_keywords_count",
                            "evidence_text",
                            "evidence_urls",
                            "requires_human_review",
                            "audit_notes",
                        ],
                    },
                }
            },
            "required": ["items"],
        }
