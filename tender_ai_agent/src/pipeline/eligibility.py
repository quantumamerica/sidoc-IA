from __future__ import annotations

from models.schemas import (
    EligibilityResult,
    EligibilityStatus,
    OpportunityCandidate,
    PipelineStage,
    RejectedOpportunity,
    RejectionReason,
)
from utils.dates import deadline_still_open, possible_dates

# Paginas que no son una licitacion: notas de prensa, planes de compras, listados de agregadores.
NOT_A_TENDER_TERMS = (
    "plan de passation des marches",
    "plan de passation des marchés",
    "procurement plan",
    "plan anual de adquisiciones",
    "plan anual de compras",
    "plano anual de contratacoes",
    "plano anual de contratações",
    "energy news",
    "tender volume",
    "press release",
    "nota de prensa",
)


class EligibilityService:
    def __init__(self, deadline_grace_days: int = 0) -> None:
        self.deadline_grace_days = deadline_grace_days

    def filter(self, candidates: list[OpportunityCandidate]) -> tuple[list[OpportunityCandidate], list[RejectedOpportunity]]:
        approved: list[OpportunityCandidate] = []
        rejected: list[RejectedOpportunity] = []

        for candidate in candidates:
            result = self.evaluate(candidate)
            if result.is_eligible:
                approved.append(candidate)
            else:
                rejected.append(
                    RejectedOpportunity(
                        **candidate.model_dump(),
                        title=candidate.titulo_estudio,
                        stage=PipelineStage.ELIGIBILITY,
                        reason=result.reason or "No cumple criterios de elegibilidad.",
                    )
                )

        return approved, rejected

    def evaluate(self, candidate: OpportunityCandidate) -> EligibilityResult:
        text = " ".join(
            value or ""
            for value in [
                candidate.raw_title,
                candidate.normalized_title,
                candidate.titulo_estudio,
                candidate.description_raw,
                candidate.descripcion,
                candidate.category,
                candidate.categoria,
            ]
        ).lower()
        if candidate.normalized_title is None:
            fallback_title = candidate.raw_title or candidate.titulo_estudio
            if fallback_title and fallback_title.strip():
                candidate.normalized_title = fallback_title.strip()
            else:
                return EligibilityResult(
                    candidate=candidate,
                    is_eligible=False,
                    reason=RejectionReason.MISSING_NORMALIZED_TITLE,
                )
        title = " ".join(
            value or "" for value in [candidate.raw_title, candidate.normalized_title, candidate.titulo_estudio]
        ).lower()
        if any(term in title for term in NOT_A_TENDER_TERMS):
            return EligibilityResult(candidate=candidate, is_eligible=False, reason=RejectionReason.NOT_A_TENDER)
        # El texto original permite probar la lectura dd/mm y mm/dd; la fecha normalizada ya eligio una.
        deadlines = [
            value
            for value in (candidate.deadline_raw, candidate.deadline_normalized, candidate.deadline)
            if value and possible_dates(value)
        ]
        if deadlines and not any(deadline_still_open(value, grace_days=self.deadline_grace_days) for value in deadlines):
            return EligibilityResult(candidate=candidate, is_eligible=False, reason=RejectionReason.DEADLINE_EXPIRED)
        if any(term in text for term in ["epc", "civil works", "construction", "obra", "construccion", "construcción"]):
            return EligibilityResult(candidate=candidate, is_eligible=False, reason=RejectionReason.EPC_OR_WORKS)
        if any(term in text for term in ["equipment supply", "supply of equipment", "suministro", "equipamiento"]):
            return EligibilityResult(candidate=candidate, is_eligible=False, reason=RejectionReason.EQUIPMENT_SUPPLY)
        candidate.eligibility_status = EligibilityStatus.ELIGIBLE
        return EligibilityResult(candidate=candidate, is_eligible=True)
