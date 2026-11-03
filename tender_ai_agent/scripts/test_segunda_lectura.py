"""Segunda lectura con Claude sobre los resultados web de Perplexity (cliente simulado, sin red)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from clients.base import ProviderResponse
from config.settings import load_settings
from models.schemas import ProviderName, RawProviderResponse
from pipeline.identification import IdentificationService
from pipeline.search_results_reader import SearchResultsReader

SETTINGS = load_settings(PROJECT_ROOT).model_copy(update={"second_reader_enabled": True})

SEARCH_RESULTS = [
    {
        "title": "Development Bank of... - Services: Rfp140/2026",
        "url": "https://www.protenders.co.za/tender/appointment-of-a-consultant-jtfm",
        "date": "2026-08-19",
        "snippet": "Development Bank of Southern Africa. RFP140.2026 APPOINTMENT OF A CONSULTANT TO DESIGN A JUST TRANSITION FINANCE MECHANISM",
    },
    {
        "title": "AfDB, EPRA Push Reform of Electricity Tariff Systems in Nairobi",
        "url": "https://news.example/afdb-epra",
        "date": "2026-10-01",
        "snippet": "News article",
    },
]


class FakeClient:
    def __init__(self, content: str | None = None, error: str | None = None) -> None:
        self.content, self.error, self.prompts = content, error, []

    def is_configured(self) -> bool:
        return True

    def run_agent(self, prompt, response_format="json", stage=None, json_schema=None):
        self.prompts.append(prompt)
        return ProviderResponse(
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-5-5",
            content=self.content,
            estimated_cost=0.004,
            metadata={"served_model": "claude-sonnet-5-5"},
            error=self.error,
        )


def raw(content: str = '{"items":[]}', results=SEARCH_RESULTS) -> RawProviderResponse:
    return RawProviderResponse(
        provider=ProviderName.PERPLEXITY,
        region="africa",
        source_id="open_web_africa_climate_finance_transition",
        source_name="Open Web Discovery - africa - Climate finance",
        prompt_name="agents/open_web_discovery_agent.md",
        content=content,
        raw_payload={"search_results": results},
        cost_estimate_usd=0.01,
        metadata={"discovery_mode": "open_web", "theme_name": "Climate finance"},
    )


def test_extracts_items_with_result_urls() -> None:
    reply = {
        "items": [
            {"result_index": 1, "raw_title": "RFP140/2026 Consultant to design a Just Transition Finance Mechanism", "contracting_authority": "DBSA"},
            {"result_index": 7, "raw_title": "indice inventado"},
            {"result_index": 1, "raw_title": "repetido"},
        ]
    }
    client = FakeClient(json.dumps(reply))
    response = SearchResultsReader(SETTINGS, client=client).maybe_read(raw(), busqueda="Tema: Climate finance")
    items = json.loads(response.content)["items"]
    assert len(items) == 1, items
    item = items[0]
    assert item["official_url"] == SEARCH_RESULTS[0]["url"], "la URL sale del resultado, no del modelo"
    assert item["contracting_authority"] == "DBSA" and item["requires_human_review"]
    assert response.metadata["second_reader"]["items"] == 1
    assert response.metadata["perplexity_content"] == '{"items":[]}'
    assert abs(response.cost_estimate_usd - 0.014) < 1e-9
    assert "[2] AfDB, EPRA" in client.prompts[0] and "Tema: Climate finance" in client.prompts[0]
    [candidate] = IdentificationService().identify([response])
    assert candidate.raw_title.startswith("RFP140/2026") and candidate.region == "africa"


def test_skips_when_perplexity_returned_items_or_no_results() -> None:
    client = FakeClient('{"items":[]}')
    reader = SearchResultsReader(SETTINGS, client=client)
    full = raw(content='{"items":[{"raw_title":"x","official_url":"https://x"}]}')
    assert reader.maybe_read(full, busqueda="b").content == full.content
    assert reader.maybe_read(raw(results=[]), busqueda="b").content == '{"items":[]}'
    assert client.prompts == []


def test_error_keeps_response() -> None:
    response = SearchResultsReader(SETTINGS, client=FakeClient(error="timeout")).maybe_read(raw(), busqueda="b")
    assert response.content == '{"items":[]}'
    assert response.metadata["second_reader"]["error"] == "timeout"


def test_disabled_by_setting() -> None:
    settings = SETTINGS.model_copy(update={"second_reader_enabled": False})
    client = FakeClient('{"items":[{"result_index":1,"raw_title":"x"}]}')
    assert SearchResultsReader(settings, client=client).maybe_read(raw(), busqueda="b").content == '{"items":[]}'


def test_reads_up_to_configured_limit() -> None:
    many = [{"title": f"r{i}", "url": f"https://ex.org/{i}", "snippet": "s"} for i in range(50)]
    client = FakeClient('{"items":[]}')
    reader = SearchResultsReader(SETTINGS.model_copy(update={"second_reader_max_results": 30}), client=client)
    response = reader.maybe_read(raw(results=many), busqueda="b")
    assert response.metadata["second_reader"]["results"] == 30
    assert "[30] r29" in client.prompts[0] and "[31]" not in client.prompts[0]


def main() -> None:
    test_extracts_items_with_result_urls()
    test_skips_when_perplexity_returned_items_or_no_results()
    test_error_keeps_response()
    test_disabled_by_setting()
    test_reads_up_to_configured_limit()
    print("OK segunda lectura")


if __name__ == "__main__":
    main()
