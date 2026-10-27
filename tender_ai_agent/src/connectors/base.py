from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import ConfigDict

from config.settings import Settings
from models.schemas import ProviderName, RawProviderResponse, SerializableModel

logger = logging.getLogger(__name__)


class ConnectorConfig(SerializableModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    enabled: bool = False
    region: str
    country: str | None = None
    language: str | None = None
    lookback_days: int = 3
    endpoint: str
    sector_terms: list[str]
    service_terms: list[str]

    def extra(self, key: str, default: Any = None) -> Any:
        return (self.model_extra or {}).get(key, default)


@dataclass
class ConnectorResult:
    connector_id: str
    fetched: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # Titulos que no pasaron el filtro, para ajustar los terminos con `conectores --probar --ver-descartados`.
    unmatched_titles: list[str] = field(default_factory=list)


def normalize(text: str | None) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _starts_word(term: str, normalized_text: str) -> bool:
    """El termino tiene que empezar una palabra: 'power' no matchea 'empowerment', 'energi' si matchea 'energia'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(normalize(term)), normalized_text) is not None


def _retry_after(value: str | None, *, default: float) -> float:
    try:
        return min(max(float(value), 1.0), 60.0) if value else default
    except ValueError:
        return default


class BaseConnector:
    """Trae avisos de un portal y los devuelve con la forma de los items de discovery."""

    MAX_RETRIES = 3
    UNMATCHED_SAMPLE = 30

    def __init__(self, config: ConnectorConfig, settings: Settings) -> None:
        self.config = config
        self.settings = settings
        self._sleep = time.sleep
        self._requests_made = 0

    def fetch(self, today: date) -> ConnectorResult:
        result = ConnectorResult(connector_id=self.config.id)
        since = today - timedelta(days=self.config.lookback_days)
        try:
            for record in self._records(since, today):
                result.fetched += 1
                item = self._to_item(record)
                if item is None:
                    continue
                matched = self.matched_terms(f"{item.get('raw_title') or ''} {item.get('description_raw') or ''}")
                if matched:
                    item["matched_keywords"] = matched
                    item["matched_keywords_count"] = len(matched)
                    result.items.append(item)
                elif len(result.unmatched_titles) < self.UNMATCHED_SAMPLE:
                    result.unmatched_titles.append(item["raw_title"])
        except Exception as exc:
            logger.warning("Conector %s fallo: %s", self.config.id, exc)
            result.error = str(exc)
        logger.info(
            "Conector %s: %s avisos leidos, %s pasan el filtro de palabras clave%s",
            self.config.id,
            result.fetched,
            len(result.items),
            f" (error: {result.error})" if result.error else "",
        )
        return result

    def matched_terms(self, text: str) -> list[str]:
        normalized = normalize(text)
        sectors = [term for term in self.config.sector_terms if _starts_word(term, normalized)]
        services = [term for term in self.config.service_terms if _starts_word(term, normalized)]
        return [*sectors, *services] if sectors and services else []

    def _records(self, since: date, until: date):
        raise NotImplementedError

    def _to_item(self, record: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError

    def _get(self, url: str, params: dict[str, Any]) -> Any:
        import requests

        pause = float(self.config.extra("request_pause_seconds", 0) or 0)
        if pause and self._requests_made:
            self._sleep(pause)
        self._requests_made += 1
        for attempt in range(self.MAX_RETRIES + 1):
            response = requests.get(url, params=params, timeout=self.settings.request_timeout_seconds)
            if response.status_code in (429, 503) and attempt < self.MAX_RETRIES:
                wait = _retry_after(response.headers.get("Retry-After"), default=5 * 2**attempt)
                logger.info("Conector %s: el portal pide esperar (%s), reintento en %ss", self.config.id, response.status_code, wait)
                self._sleep(wait)
                continue
            response.raise_for_status()
            return response.json()

    def _item(
        self,
        *,
        title: str | None,
        url: str | None,
        authority: str | None,
        description: str | None,
        deadline: str | None,
        published: str | None,
        reference: str | None,
        country: str | None = None,
        notes: list[str] | None = None,
    ) -> dict[str, Any] | None:
        title = (title or "").strip()
        if not title or not url:
            return None
        description = (description or "").strip() or None
        return {
            "source_id": f"api_{self.config.id}",
            "source_name": self.config.name,
            "source_url": self.config.endpoint,
            "raw_title": title,
            "normalized_title": title,
            "official_url": url,
            "all_urls": [url],
            "contracting_authority": authority,
            "country": country or self.config.country,
            "deadline_raw": deadline,
            "publication_date_raw": published,
            "description_raw": description,
            "language": self.config.language,
            "referencia": reference,
            "evidence_text": (description or title)[:2000],
            "evidence_urls": [url],
            "requires_human_review": False,
            "audit_notes": [f"Cargada por el conector {self.config.id} desde la API del portal.", *(notes or [])],
        }


def to_raw_response(provider: ProviderName, region: str, run_id: str, result: ConnectorResult, config: ConnectorConfig) -> RawProviderResponse:
    return RawProviderResponse(
        provider=provider,
        region=region,
        source_id=f"api_{config.id}",
        source_name=config.name,
        source_url=config.endpoint,
        run_id=run_id,
        prompt_name=f"connector:{config.id}",
        content=json.dumps({"items": result.items}, ensure_ascii=False),
        raw_payload={"fetched": result.fetched, "error": result.error},
        cost_estimate_usd=0.0,
        metadata={
            "discovery_mode": "api",
            "source_name": config.name,
            "connector_id": config.id,
            "fetched": result.fetched,
            "matched": len(result.items),
            "error": result.error,
        },
    )
