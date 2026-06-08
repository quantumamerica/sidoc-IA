from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from models.schemas import OpportunityCandidate, ProviderName, RawProviderResponse

logger = logging.getLogger(__name__)


class IdentificationService:
    def identify(self, responses: list[RawProviderResponse]) -> list[OpportunityCandidate]:
        candidates: list[OpportunityCandidate] = []
        for response in responses:
            candidates.extend(self._parse_response(response))
        return candidates

    def _parse_response(self, response: RawProviderResponse) -> list[OpportunityCandidate]:
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Respuesta no parseable como JSON source_id=%s provider=%s", response.source_id, response.provider)
            return []

        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("candidates") or []

        if not isinstance(payload, list):
            return []

        provider = ProviderName(response.provider)
        candidates: list[OpportunityCandidate] = []
        for item in payload:
            if isinstance(item, dict):
                metadata = dict(item.get("metadata") or {})
                metadata["raw_response_metadata"] = response.metadata
                item_with_provider: dict[str, Any] = {
                    **item,
                    "provider": provider,
                    "region": response.region,
                    "discovered_by_prompt": response.prompt_name,
                    "raw_response_path": response.raw_response_path,
                    "metadata": metadata,
                }
                if not item_with_provider.get("source_id"):
                    item_with_provider["source_id"] = response.source_id
                if not item_with_provider.get("source_name"):
                    item_with_provider["source_name"] = response.source_name
                if not item_with_provider.get("source_url"):
                    item_with_provider["source_url"] = response.source_url
                try:
                    candidates.append(OpportunityCandidate.model_validate(item_with_provider))
                except ValidationError as exc:
                    logger.warning(
                        "Candidata descartada por validacion Pydantic source_id=%s provider=%s error=%s",
                        response.source_id,
                        response.provider,
                        exc,
                    )
        return candidates
