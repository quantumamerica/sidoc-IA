from __future__ import annotations

from models.schemas import (
    EnrichedOpportunity,
    PipelineStage,
    RejectedOpportunity,
    RejectionReason,
    ValidatedOpportunity,
    ValidationResult,
)
from utils.dates import is_future_date


class ValidationService:
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
        deadline = opportunity.deadline_normalized or opportunity.deadline
        if deadline and not is_future_date(deadline):
            return ValidationResult(opportunity=opportunity, is_valid=False, reason=RejectionReason.DEADLINE_EXPIRED)
        if not opportunity.evidence_text and not opportunity.evidence_urls:
            return ValidationResult(opportunity=opportunity, is_valid=False, reason=RejectionReason.INSUFFICIENT_EVIDENCE)
        return ValidationResult(opportunity=opportunity, is_valid=True)
