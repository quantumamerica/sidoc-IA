from __future__ import annotations

import json
import logging
from typing import Any

from clients.anthropic_client import AnthropicClient
from config.settings import Settings
from models.schemas import RawProviderResponse
from utils.dates import today_utc_date
from utils.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)

PROMPT_PATH = "agents/search_results_reader_agent.md"
SNIPPET_CHARS = 500

READER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "result_index": {"type": "integer"},
                    "raw_title": {"type": "string"},
                    "contracting_authority": {"type": "string"},
                    "country": {"type": "string"},
                    "deadline_raw": {"type": "string"},
                    "publication_date_raw": {"type": "string"},
                    "description_raw": {"type": "string"},
                    "language": {"type": "string"},
                },
                "required": ["result_index", "raw_title", "language"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _response_items(content: str | None) -> list[Any]:
    try:
        payload = json.loads(content or "")
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("candidates") or []
    return payload if isinstance(payload, list) else []


class SearchResultsReader:
    """Segunda lectura: cuando Perplexity devuelve una lista vacia pero trajo resultados web,
    Claude lee esos resultados (titulo, fragmento, fecha) y extrae las convocatorias.

    En las corridas del 29 y 30-oct-2026, 99 de 112 busquedas tenian resultados web y volvian vacias.
    Lo que se extrae sigue el pipeline normal: elegibilidad, calidad de contenido y juez.
    """

    def __init__(
        self,
        settings: Settings,
        client: AnthropicClient | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.settings = settings
        if client is None:
            client = AnthropicClient(settings)
            client.model = settings.second_reader_model
        self.client = client
        self.prompt_loader = prompt_loader or PromptLoader(settings.prompts_dir)

    def enabled(self) -> bool:
        return self.settings.second_reader_enabled and self.client.is_configured()

    def maybe_read(self, response: RawProviderResponse, *, busqueda: str) -> RawProviderResponse:
        """Devuelve la misma respuesta, con los items extraidos si correspondia una segunda lectura."""
        if not self.enabled() or _response_items(response.content):
            return response
        results = self._search_results(response.raw_payload, self.settings.second_reader_max_results)
        if not results:
            return response
        try:
            items, meta = self._read(response, results, busqueda=busqueda)
        except Exception as exc:  # nunca corta la corrida
            logger.warning("Segunda lectura fallo source_id=%s: %s", response.source_id, exc)
            response.metadata["second_reader"] = {"error": str(exc), "results": len(results)}
            return response
        response.metadata["second_reader"] = {**meta, "results": len(results), "items": len(items)}
        response.metadata["perplexity_content"] = response.content
        response.content = json.dumps({"items": items}, ensure_ascii=False)
        if meta.get("cost") is not None:
            response.cost_estimate_usd = (response.cost_estimate_usd or 0.0) + meta["cost"]
        logger.info(
            "Segunda lectura source_id=%s resultados=%s convocatorias=%s",
            response.source_id,
            len(results),
            len(items),
        )
        return response

    @staticmethod
    def _search_results(raw_payload: dict[str, Any] | None, limit: int) -> list[dict[str, Any]]:
        results = (raw_payload or {}).get("search_results") or []
        return [r for r in results if isinstance(r, dict) and r.get("url")][: max(1, limit)]

    def _read(
        self, response: RawProviderResponse, results: list[dict[str, Any]], *, busqueda: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        lines = []
        for index, result in enumerate(results, start=1):
            snippet = " ".join(str(result.get("snippet") or "").split())[:SNIPPET_CHARS]
            lines.append(
                f"[{index}] {result.get('title') or ''}\n"
                f"    fecha: {result.get('date') or '-'} | actualizado: {result.get('last_updated') or '-'}\n"
                f"    fragmento: {snippet}"
            )
        prompt = self.prompt_loader.render_file(
            PROMPT_PATH,
            {
                "fecha_actual": today_utc_date().isoformat(),
                "region": response.region,
                "busqueda": busqueda,
                "resultados": "\n".join(lines),
            },
        )
        reply = self.client.run_agent(prompt, response_format="json", stage="second_reader", json_schema=READER_SCHEMA)
        if reply.error:
            raise RuntimeError(reply.error)
        meta = {"model": (reply.metadata or {}).get("served_model") or reply.model, "cost": reply.estimated_cost}
        return self._to_items(_response_items(reply.content), results, response), meta

    def _to_items(
        self, extracted: list[Any], results: list[dict[str, Any]], response: RawProviderResponse
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[int] = set()
        for entry in extracted:
            if not isinstance(entry, dict):
                continue
            index = entry.get("result_index")
            # La URL sale del resultado, nunca del modelo.
            if not isinstance(index, int) or not 1 <= index <= len(results) or index in seen:
                continue
            seen.add(index)
            result = results[index - 1]
            title = str(entry.get("raw_title") or result.get("title") or "").strip()
            if not title:
                continue
            snippet = " ".join(str(result.get("snippet") or "").split())
            url = result["url"]
            items.append(
                {
                    "raw_title": title,
                    "normalized_title": title,
                    "official_url": url,
                    "all_urls": [url],
                    "contracting_authority": entry.get("contracting_authority") or None,
                    "country": entry.get("country") or None,
                    "deadline_raw": entry.get("deadline_raw") or None,
                    "publication_date_raw": entry.get("publication_date_raw") or result.get("date") or None,
                    "description_raw": entry.get("description_raw") or snippet[:1000] or None,
                    "language": entry.get("language") or None,
                    "evidence_text": snippet[:2000] or title,
                    "evidence_urls": [url],
                    "requires_human_review": True,
                    "audit_notes": [
                        "Extraida por la segunda lectura (Claude) de los resultados web de Perplexity: verificar el aviso en la URL."
                    ],
                }
            )
        return items
