from __future__ import annotations

from models.schemas import DeduplicationResult, PipelineStage, RejectedOpportunity, RejectionReason, ValidatedOpportunity


class DeduplicationService:
    def deduplicate(self, opportunities: list[ValidatedOpportunity]) -> list[ValidatedOpportunity]:
        return self.deduplicate_with_result(opportunities).unique_opportunities

    def deduplicate_with_result(self, opportunities: list[ValidatedOpportunity]) -> DeduplicationResult:
        seen: set[str] = set()
        groups: dict[str, list[str]] = {}
        unique: list[ValidatedOpportunity] = []
        duplicates: list[ValidatedOpportunity] = []
        rejected: list[RejectedOpportunity] = []

        for opportunity in opportunities:
            key = self._dedup_key(opportunity)
            if key in seen:
                opportunity.duplicate_group_id = key
                duplicates.append(opportunity)
                rejected.append(
                    RejectedOpportunity(
                        **opportunity.model_dump(),
                        stage=PipelineStage.DEDUPLICATION,
                        reason=RejectionReason.DUPLICATE,
                    )
                )
                continue
            seen.add(key)
            opportunity.duplicate_group_id = key
            unique.append(opportunity)
            groups.setdefault(key, []).append(opportunity.official_url or opportunity.url or opportunity.titulo_estudio or "")

        return DeduplicationResult(
            unique_opportunities=unique,
            duplicate_opportunities=duplicates,
            duplicate_groups=groups,
            rejected_duplicates=rejected,
        )

    @staticmethod
    def _dedup_key(opportunity: ValidatedOpportunity) -> str:
        if opportunity.official_url or opportunity.url:
            return (opportunity.official_url or opportunity.url or "").strip().lower()
        return "|".join(
            [
                opportunity.fuente or "",
                opportunity.referencia or "",
                opportunity.titulo_estudio or "",
                str(opportunity.deadline or ""),
            ]
        ).lower()
