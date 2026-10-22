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
from pipeline.eligibility import EligibilityService
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


def main() -> None:
    test_dates()
    test_eligibility()
    test_judge()
    print("OK")


if __name__ == "__main__":
    main()
