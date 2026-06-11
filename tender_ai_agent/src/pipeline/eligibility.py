from __future__ import annotations

from models.schemas import (
    EligibilityResult,
    EligibilityStatus,
    OpportunityCandidate,
    PipelineStage,
    RejectedOpportunity,
    RejectionReason,
)
from utils.dates import is_future_date


class EligibilityService:
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
        deadline = candidate.deadline_normalized or candidate.deadline
        if deadline and not is_future_date(deadline):
            return EligibilityResult(candidate=candidate, is_eligible=False, reason=RejectionReason.DEADLINE_EXPIRED)
        if any(term in text for term in ["epc", "civil works", "construction", "obra", "construccion", "construcción"]):
            return EligibilityResult(candidate=candidate, is_eligible=False, reason=RejectionReason.EPC_OR_WORKS)
        if any(term in text for term in ["equipment supply", "supply of equipment", "suministro", "equipamiento"]):
            return EligibilityResult(candidate=candidate, is_eligible=False, reason=RejectionReason.EQUIPMENT_SUPPLY)
        candidate.eligibility_status = EligibilityStatus.ELIGIBLE
        return EligibilityResult(candidate=candidate, is_eligible=True)
