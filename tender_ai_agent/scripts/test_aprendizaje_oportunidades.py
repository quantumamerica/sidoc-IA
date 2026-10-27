"""Ajustes del aprendizaje de oportunidades aceptadas: plazo con gracia, not_a_tender y juez IA."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from models.schemas import CandidateOpportunity, ProviderName, RejectionReason
from pipeline.ai_validation import AiBusinessValidationService
from pipeline.eligibility import EligibilityService, is_listing_url
from utils.dates import deadline_still_open, possible_dates, today_utc_date


def candidate(title: str, deadline: str) -> CandidateOpportunity:
    return CandidateOpportunity(
        provider=ProviderName.OPENAI,
        region="africa",
        source_id="test",
        source_name="Test",
        official_url="https://example.org/tender/1",
        raw_title=title,
        deadline_raw=deadline,
        description_raw="Consulting services for electricity tariff review.",
    )


def test_dates() -> None:
    ref = date(2026, 10, 21)
    # dd/mm y mm/dd ambiguas: se prueban las dos lecturas
    assert set(possible_dates("03/11/2026")) == {date(2026, 11, 3), date(2026, 3, 11)}
    assert possible_dates("25/12/2026") == [date(2026, 12, 25)]
    assert deadline_still_open("2026-10-21", reference_date=ref)
    assert not deadline_still_open("2026-10-20", reference_date=ref)
    assert deadline_still_open("2026-10-20", grace_days=1, reference_date=ref)
    assert deadline_still_open("11/03/2026", reference_date=ref)  # 3-nov si es mm/dd


def test_eligibility() -> None:
    future = (today_utc_date() + timedelta(days=20)).isoformat()
    yesterday = (today_utc_date() - timedelta(days=1)).isoformat()
    service = EligibilityService(deadline_grace_days=1)

    result = service.evaluate(candidate("Plan de Passation des Marchés - Projet DREAM", future))
    assert result.reason == RejectionReason.NOT_A_TENDER, result.reason
    assert service.evaluate(candidate("Electricity tariff policy study", yesterday)).is_eligible
    strict = EligibilityService(deadline_grace_days=0)
    assert strict.evaluate(candidate("Electricity tariff policy study", yesterday)).reason == RejectionReason.DEADLINE_EXPIRED


def test_judge() -> None:
    judge = AiBusinessValidationService.__new__(AiBusinessValidationService)
    judge.threshold = 0.6
    base = {"relevance_score": 0.9, "is_consulting": True, "is_works_or_equipment": False, "decision": "SI", "reason": "ok"}
    # Sin el campo nuevo (respuestas viejas) se comporta como antes
    assert judge._interpret(base).approved
    verdict = judge._interpret({**base, "is_tender_notice": False})
    assert not verdict.approved and verdict.rejection_reason == RejectionReason.NOT_A_TENDER


def test_listing_urls() -> None:
    assert is_listing_url("https://www.adb.org/status/active?page=74")
    assert is_listing_url("https://www.olacde.org/en/current-procurement/")
    assert not is_listing_url("https://nowgrenada.com/2026/10/reoi-regulatory-development-consulting-services-for-cegeb/")
    assert not is_listing_url(
        "https://procontract.due-north.com/Advert?advertId=dca9f82c-6bcc-f111-8141-6045bdf14b1f&p=527b4bbd-5c58-e511-80ef-000c29c9ba21"
    )
    service = EligibilityService()
    listing = candidate("ADB active projects", (today_utc_date() + timedelta(days=20)).isoformat())
    listing.official_url = "https://www.adb.org/status/active?page=74"
    assert service.evaluate(listing).reason == RejectionReason.NOT_A_TENDER


def test_judge_client_selection() -> None:
    from clients.judge import build_judge_client
    from config.settings import load_settings

    settings = load_settings(PROJECT_ROOT)
    with_key = settings.model_copy(update={"ai_judge_provider": "anthropic", "anthropic_api_key": "test"})
    assert build_judge_client(with_key).provider == ProviderName.ANTHROPIC
    without_key = settings.model_copy(update={"ai_judge_provider": "anthropic", "anthropic_api_key": None})
    assert build_judge_client(without_key).provider == ProviderName.GEMINI
    forced = settings.model_copy(update={"ai_judge_provider": "gemini", "anthropic_api_key": "test"})
    assert build_judge_client(forced).provider == ProviderName.GEMINI


def test_anthropic_client() -> None:
    import json
    from types import SimpleNamespace

    import anthropic

    from clients.anthropic_client import AnthropicClient
    from config.settings import load_settings

    calls = []
    verdict = {"relevance_score": 0.8, "is_consulting": True, "is_works_or_equipment": False,
               "is_tender_notice": True, "decision": "SI", "reason": "ok"}

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                stop_details=None,
                model=kwargs["model"],
                content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(verdict))],
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
                to_dict=lambda: {},
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.beta = SimpleNamespace(messages=FakeMessages())

    original = anthropic.Anthropic
    anthropic.Anthropic = FakeClient
    try:
        settings = load_settings(PROJECT_ROOT).model_copy(update={"anthropic_api_key": "test", "anthropic_model": "claude-opus-5-5"})
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        response = AnthropicClient(settings).run_agent("prompt", stage="ai_validation", json_schema=schema)
    finally:
        anthropic.Anthropic = original

    assert response.ok and response.parsed_json == verdict, response.error
    request = calls[0]
    assert request["output_config"]["format"] == {"type": "json_schema", "schema": schema}
    assert request["fallbacks"] == "default" and "temperature" not in request
    assert abs(response.estimated_cost - (1000 * 4 + 100 * 20) / 1_000_000) < 1e-12


def test_ia_trace_mapping() -> None:
    from models.schemas import IA_TRACE_COLUMNS, ValidatedOpportunity
    from pipeline.db_mapping import DbMappingService
    from storage.repositories import OpportunityRepository

    opportunity = ValidatedOpportunity(
        provider=ProviderName.PERPLEXITY,
        region="latam",
        source_id="x",
        source_name="Now Grenada",
        official_url="https://nowgrenada.com/2026/10/reoi-cegeb/",
        raw_title="REOI regulatory development consulting",
        description_raw="Consulting services for regulatory development.",
        ai_confidence=0.85,
        metadata={
            "raw_response_metadata": {"discovery_mode": "open_web", "theme_name": "Electricity tariffs"},
            "ai_judge": {"model": "claude-opus-5-5", "score": 0.85, "reason": "REOI concreta de regulacion."},
        },
    )
    mapped = DbMappingService().map_one(opportunity)
    row = mapped.to_db_dict()
    assert row["ia_modalidad"] == "open_web" and row["ia_busqueda"] == "Electricity tariffs"
    assert row["ia_modelo_juez"] == "claude-opus-5-5" and row["ia_puntaje"] == 0.85
    assert row["ia_evidencia_url"] == "https://nowgrenada.com/2026/10/reoi-cegeb/"

    # Tabla sin las columnas ia_*: se omiten sin error.
    from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

    engine = create_engine("sqlite://")
    table = Table("licitacion", MetaData(), Column("id", Integer, primary_key=True), Column("url", String), Column("titulo_estudio", String))
    table.metadata.create_all(engine)
    repository = OpportunityRepository(engine, "licitacion")
    result = repository.insert_opportunity(mapped)
    assert result.inserted, result.error
    missing = repository.validate_expected_columns()
    assert set(IA_TRACE_COLUMNS) <= set(missing)


def main() -> None:
    test_dates()
    test_eligibility()
    test_judge()
    test_listing_urls()
    test_judge_client_selection()
    test_anthropic_client()
    test_ia_trace_mapping()
    print("OK")


if __name__ == "__main__":
    main()
