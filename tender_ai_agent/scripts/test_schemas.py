from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from models.schemas import (
    CandidateOpportunity,
    CostReport,
    DbMappedOpportunity,
    EligibilityStatus,
    PipelineRun,
    PipelineStage,
    PipelineStageLog,
    ProcessType,
    ProviderComparisonResult,
    ProviderName,
    RawProviderResult,
    RejectedOpportunity,
    RejectionReason,
    Source,
    ValidatedOpportunity,
)
from utils.dates import normalize_date, today_utc_date


def main() -> None:
    future_deadline = today_utc_date() + timedelta(days=30)

    source = Source(
        id="iadb",
        name="Inter-American Development Bank Procurement",
        region="latam",
        source_type="multilateral",
        url="https://www.iadb.org/en/project-procurement",
    )

    raw_result = RawProviderResult(
        provider=ProviderName.OPENAI,
        region=source.region,
        source_id=source.id,
        source_name=source.name,
        source_url=source.url,
        prompt_name="latam.md",
        content="[]",
    )

    candidate = CandidateOpportunity(
        provider=ProviderName.OPENAI,
        region="latam",
        source_id=source.id,
        source_name=source.name,
        official_url="https://example.org/tender/123",
        raw_title="Tariff study for electricity distribution",
        contracting_authority="Energy Regulator",
        country="Exampleland",
        process_type=ProcessType.RFP,
        deadline_raw=future_deadline.isoformat(),
        deadline_normalized=future_deadline.isoformat(),
        publication_date_raw="2026-04-01",
        publication_date_normalized="2026-04-01",
        description_raw="Consulting services for tariff review and financial modeling.",
        description_summary="Tariff review and financial modeling consulting assignment.",
        language="en",
        topic="electricity tariffs",
        category="energy regulation",
        matched_keywords=["tariff", "financial modeling", "electricity"],
        eligibility_status=EligibilityStatus.ELIGIBLE,
        evidence_text="Official procurement notice text.",
        evidence_urls=["https://example.org/tender/123"],
    )

    validated = ValidatedOpportunity(**candidate.model_dump())
    mapped = DbMappedOpportunity.from_validated(validated)

    rejected = RejectedOpportunity(
        provider=ProviderName.PERPLEXITY,
        source_id="sample",
        title="Closed EPC project",
        stage=PipelineStage.ELIGIBILITY,
        reason=RejectionReason.EPC_OR_WORKS,
    )

    pipeline_run = PipelineRun(
        run_id="demo-run",
        started_at=raw_result.discovered_at,
        dry_run=True,
        region="latam",
        providers=[ProviderName.OPENAI, ProviderName.PERPLEXITY],
        stage_logs=[
            PipelineStageLog(
                run_id="demo-run",
                stage=PipelineStage.IDENTIFICATION,
                provider=ProviderName.OPENAI,
                region="latam",
                input_count=1,
                output_count=1,
            )
        ],
        cost_report=CostReport(provider=ProviderName.OPENAI, run_id="demo-run", estimated_usd=None),
        comparison={"demo": ProviderComparisonResult(run_id="demo-run").to_json_dict()},
    )

    assert candidate.deadline_is_future()
    assert mapped.to_db_dict()["deadline"] == future_deadline.isoformat()
    assert "provider" in mapped.internal_metadata()
    assert rejected.motivo_rechazo == RejectionReason.EPC_OR_WORKS.value
    assert normalize_date("03/06/2026 11:00UK Time").isoformat() == "2026-06-03"

    raw_deadline_candidate = CandidateOpportunity(
        provider=ProviderName.PERPLEXITY,
        region="eastern_europe",
        source_id="ebrd",
        source_name="EBRD Client E-Procurement Portal",
        official_url="https://ecepp.ebrd.com/delta/noticeSearchResults.html",
        raw_title="Serbia: PIU Support Consultant for Phase III of the Project",
        deadline_raw="03/06/2026 11:00UK Time",
        description_raw="PIU Support Consultant for Phase III of the Project",
    )
    assert raw_deadline_candidate.deadline_normalized.isoformat() == "2026-06-03"

    print(
        json.dumps(
            {
                "source": source.to_json_dict(exclude_none=True),
                "raw_result": raw_result.to_json_dict(exclude_none=True),
                "db_payload": mapped.to_db_dict(),
                "internal_metadata_keys": sorted(mapped.internal_metadata().keys()),
                "rejected": rejected.to_json_dict(exclude_none=True),
                "pipeline_run": pipeline_run.to_json_dict(exclude_none=True),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
