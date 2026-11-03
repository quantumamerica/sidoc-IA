"""Busqueda por la Agent API de Perplexity (requests simulado, sin red)."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from clients.perplexity_client import PerplexityClient
from config.settings import load_settings

BASE = load_settings(PROJECT_ROOT).model_copy(update={"perplexity_api_key": "x"})

AGENT_OK = {
    "id": "resp_1",
    "output": [
        {"type": "search_results", "results": [
            {"id": 1, "title": "RFP Tariff Study", "url": "https://ex.org/rfp", "snippet": "Consultancy", "date": "2026-10-30"},
            {"id": 2, "title": "dup", "url": "https://ex.org/rfp"},
        ]},
        {"type": "message", "content": [{"type": "output_text", "text": '{"items":[{"raw_title":"RFP Tariff Study"}]}'}]},
    ],
    "usage": {"input_tokens": 100, "output_tokens": 20, "cost": {"total_cost": 0.02}},
}
SONAR_OK = {"choices": [{"message": {"content": '{"items":[]}'}}], "usage": {}, "search_results": []}


class FakeResponse:
    def __init__(self, status: int, data: dict) -> None:
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def install(responses: dict[str, FakeResponse]) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls.append((url, json))
        return responses[url]

    sys.modules["requests"] = types.SimpleNamespace(post=post)
    return calls


def client(**update) -> PerplexityClient:
    c = PerplexityClient(BASE.model_copy(update=update))
    c.retry_delay_seconds = 0
    return c


def test_agent_parses_text_and_results() -> None:
    calls = install({PerplexityClient.agent_endpoint: FakeResponse(200, AGENT_OK)})
    r = client().run_discovery("buscar")
    assert r.ok, r.error
    assert calls[0][0] == PerplexityClient.agent_endpoint
    body = calls[0][1]
    assert body["effort"] == "low"
    assert body["tools"][0]["type"] == "web_search"
    assert body["tools"][0]["filters"]["search_recency_filter"] == "year"
    assert body["response_format"]["type"] == "json_schema"
    assert r.parsed_json["items"][0]["raw_title"] == "RFP Tariff Study"
    assert r.raw_response["search_results"] == [
        {"title": "RFP Tariff Study", "url": "https://ex.org/rfp", "snippet": "Consultancy", "date": "2026-10-30", "last_updated": None}
    ]
    assert r.metadata["api"] == "agent"


def test_agent_error_falls_back_to_sonar() -> None:
    calls = install({
        PerplexityClient.agent_endpoint: FakeResponse(400, {"error": "bad field"}),
        PerplexityClient.endpoint: FakeResponse(200, SONAR_OK),
    })
    r = client().run_discovery("buscar")
    assert r.ok, r.error
    assert [u for u, _ in calls][-1] == PerplexityClient.endpoint
    assert r.metadata["api"] == "chat_completions"
    assert [u for u, _ in calls].count(PerplexityClient.agent_endpoint) == 1


def test_after_rejection_goes_straight_to_sonar() -> None:
    calls = install({
        PerplexityClient.agent_endpoint: FakeResponse(400, {"error": "bad field"}),
        PerplexityClient.endpoint: FakeResponse(200, SONAR_OK),
    })
    c = client()
    c.run_discovery("uno")
    c.run_discovery("dos")
    assert [u for u, _ in calls].count(PerplexityClient.agent_endpoint) == 1


def test_sonar_mode_skips_agent() -> None:
    calls = install({PerplexityClient.endpoint: FakeResponse(200, SONAR_OK)})
    r = client(perplexity_discovery_api="sonar").run_discovery("buscar")
    assert r.ok and [u for u, _ in calls] == [PerplexityClient.endpoint]


def main() -> None:
    test_agent_parses_text_and_results()
    test_agent_error_falls_back_to_sonar()
    test_after_rejection_goes_straight_to_sonar()
    test_sonar_mode_skips_agent()
    print("OK perplexity agent")


if __name__ == "__main__":
    main()
