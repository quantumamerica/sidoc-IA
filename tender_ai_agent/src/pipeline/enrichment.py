from __future__ import annotations

from models.schemas import EnrichedOpportunity, OpportunityCandidate


class EnrichmentService:
    def enrich(self, opportunities: list[OpportunityCandidate]) -> list[EnrichedOpportunity]:
        return [EnrichedOpportunity(**opportunity.model_dump()) for opportunity in opportunities]
