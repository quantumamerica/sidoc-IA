from __future__ import annotations

from models.schemas import (
    EnrichedOpportunity,
    PipelineStage,
    RejectedOpportunity,
    RejectionReason,
    ValidatedOpportunity,
    ValidationResult,
)
from utils.dates import deadline_still_open, possible_dates


class ValidationService:
    def __init__(self, deadline_grace_days: int = 0) -> None:
        self.deadline_grace_days = deadline_grace_days

    def validate(self, opportunities: list[EnrichedOpportunity]) -> tuple[list[ValidatedOpportunity], list[RejectedOpportunity]]:
        valid: list[ValidatedOpportunity] = []
        rejected: list[RejectedOpportunity] = []

        for opportunity in opportunities:
            result = self.evaluate(opportunity)
            if result.is_valid:
                valid.append(ValidatedOpportunity(**opportunity.model_dump()))
            else:
                rejected.append(
                    RejectedOpportunity(
                        **opportunity.model_dump(),
                        title=opportunity.titulo_estudio,
                        stage=PipelineStage.VALIDATION,
                        reason=result.reason or "No paso validacion.",
                    )
                )

        return valid, rejected

    def evaluate(self, opportunity: EnrichedOpportunity) -> ValidationResult:
        # El texto original permite probar la lectura dd/mm y mm/dd; la fecha normalizada ya eligio una.
        deadlines = [
            value
            for value in (opportunity.deadline_raw, opportunity.deadline_normalized, opportunity.deadline)
            if value and possible_dates(value)
        ]
        if deadlines and not any(deadline_still_open(value, grace_days=self.deadline_grace_days) for value in deadlines):
            return ValidationResult(opportunity=opportunity, is_valid=False, reason=RejectionReason.DEADLINE_EXPIRED)
        if not opportunity.evidence_text and not opportunity.evidence_urls:
            return ValidationResult(opportunity=opportunity, is_valid=False, reason=RejectionReason.INSUFFICIENT_EVIDENCE)
        return ValidationResult(opportunity=opportunity, is_valid=True)
