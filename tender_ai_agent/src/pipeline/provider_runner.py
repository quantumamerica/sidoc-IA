from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from clients.base import ProviderResponse
from clients.openai_client import OpenAIClient
from clients.perplexity_client import PerplexityClient
from config.settings import Settings
from models.schemas import (
    PipelineStage,
    PipelineStageLog,
    ProviderName,
    ProviderPipelineResult,
    ProviderRunReport,
    RawProviderResponse,
    SourceConfig,
)
from pipeline.ai_validation import AiBusinessValidationService
from pipeline.audit import AuditLogger
from pipeline.content_quality_validation import ContentQualityValidationService
from pipeline.db_mapping import DbMappingService
from pipeline.deduplication import DeduplicationService
from pipeline.discovery import DiscoveryService
from pipeline.eligibility import EligibilityService
from pipeline.enrichment import EnrichmentService
from pipeline.identification import IdentificationService
from pipeline.negocio_assignment import NegocioAssignmentService
from pipeline.validation import ValidationService
from utils.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class ProviderPipelineRunner:
    def __init__(self, settings: Settings, audit_logger: AuditLogger) -> None:
        self.settings = settings
        self.audit_logger = audit_logger
        self.discovery = DiscoveryService(settings)
        self.identification = IdentificationService()
        self.eligibility = EligibilityService()
        self.enrichment = EnrichmentService()
        self.validation = ValidationService()
        self.content_quality_validation = ContentQualityValidationService(settings)
        self.ai_validation = AiBusinessValidationService(settings)
        self.deduplication = DeduplicationService()
        self.negocio_assignment = NegocioAssignmentService(settings)
        self.db_mapping = DbMappingService(settings)

    def run(
        self,
        *,
        run_id: str,
        provider: ProviderName,
        region: str,
        region_prompt: str,
        sources: list[SourceConfig],
        omitted_sources: list[SourceConfig] | None = None,
        dry_run: bool,
    ) -> ProviderPipelineResult:
        report = ProviderRunReport(provider=provider, region=region)
        result = ProviderPipelineResult(
            run_id=run_id,
            provider=provider,
            region=region,
            sources_consulted=sources,
            sources_omitted=omitted_sources or [],
            report=report,
        )
        cost_tracker = CostTracker()

        raw_responses = self._run_stage(
            result,
            PipelineStage.DISCOVERY,
            lambda: self._discover(provider, region, region_prompt, sources, run_id, dry_run),
            input_payload=sources,
        )
        result.raw_results = raw_responses or []
        for response in result.raw_results:
            cost_tracker.add(response.cost_estimate_usd)

        candidates = self._run_stage(
            result,
            PipelineStage.IDENTIFICATION,
            lambda: self.identification.identify(result.raw_results),
            input_payload=result.raw_results,
        )
        result.candidates = candidates or []

        eligibility_output = self._run_stage(
            result,
            PipelineStage.ELIGIBILITY,
            lambda: self.eligibility.filter(result.candidates),
            input_payload=result.candidates,
        )
        if eligibility_output:
            result.eligible, rejected = eligibility_output
            result.discarded.extend(rejected)

        enriched = self._run_stage(
            result,
            PipelineStage.ENRICHMENT,
            lambda: self.enrichment.enrich(result.eligible),
            input_payload=result.eligible,
        )
        result.enriched = enriched or []

        validation_output = self._run_stage(
            result,
            PipelineStage.VALIDATION,
            lambda: self.validation.validate(result.enriched),
            input_payload=result.enriched,
        )
        if validation_output:
            result.validated, rejected = validation_output
            result.discarded.extend(rejected)

        content_quality_output = self._run_stage(
            result,
            PipelineStage.CONTENT_QUALITY_VALIDATION,
            lambda: self.content_quality_validation.validate(result.validated),
            input_payload=result.validated,
        )
        if content_quality_output:
            result.validated, content_quality_rejected = content_quality_output
            result.discarded.extend(content_quality_rejected)

        ai_validation_output = self._run_stage(
            result,
            PipelineStage.AI_VALIDATION,
            lambda: self.ai_validation.validate(result.validated),
            input_payload=result.validated,
        )
        if ai_validation_output:
            result.validated, ai_rejected = ai_validation_output
            result.discarded.extend(ai_rejected)

        dedup_output = self._run_stage(
            result,
            PipelineStage.DEDUPLICATION,
            lambda: self.deduplication.deduplicate_with_result(result.validated),
            input_payload=result.validated,
        )
        unique_validated = result.validated
        if dedup_output:
            unique_validated = dedup_output.unique_opportunities
            result.duplicates = dedup_output.rejected_duplicates
            result.discarded.extend(dedup_output.rejected_duplicates)

        assigned = self._run_stage(
            result,
            PipelineStage.NEGOCIO_ASSIGNMENT,
            lambda: self.negocio_assignment.assign(unique_validated),
            input_payload=unique_validated,
        )
        if assigned is not None:
            unique_validated = assigned

        mapped = self._run_stage(
            result,
            PipelineStage.DB_MAPPING,
            lambda: self.db_mapping.map(unique_validated),
            input_payload=unique_validated,
        )
        result.mapped = mapped or []

        report.sources_consulted = len(sources)
        report.sources_skipped = len(result.sources_omitted)
        report.raw_responses = len(result.raw_results)
        report.candidates = len(result.candidates)
        report.eligible = len(result.eligible)
        report.enriched = len(result.enriched)
        report.valid = len(result.validated)
        report.negocio_assigned = sum(1 for item in unique_validated if item.negocio_slug)
        report.duplicated = len(result.duplicates)
        report.mapped = len(result.mapped)
        report.rejected = len(result.discarded)
        report.cost_estimate_usd = cost_tracker.total_or_none()
        report.errors = result.errors

        self.audit_logger.save_stage_output(run_id, provider.value, "provider_result", result.model_dump(mode="json"), region=region)
        return result

    def _run_stage(
        self,
        result: ProviderPipelineResult,
        stage: PipelineStage,
        operation: Callable[[], Any],
        input_payload: Any | None = None,
    ) -> Any | None:
        log = PipelineStageLog(run_id=result.run_id, stage=stage, provider=result.provider, region=result.region)
        log.input_count = self._count_payload(input_payload)
        started = datetime.now(timezone.utc)
        try:
            payload = operation()
            log.finished_at = datetime.now(timezone.utc)
            log.output_count = self._count_payload(payload)
            self.audit_logger.save_stage_output(result.run_id, result.provider.value, stage.value, payload, region=result.region)
            self.audit_logger.record_stage_event(
                result.run_id,
                {
                    "provider": result.provider.value,
                    "region": result.region,
                    "stage": stage.value,
                    "status": "ok",
                    "output_count": log.output_count,
                },
            )
            logger.info(
                "Etapa completada proveedor=%s region=%s etapa=%s items=%s",
                result.provider.value,
                result.region,
                stage.value,
                log.output_count,
            )
            return payload
        except Exception as exc:
            logger.exception("Error etapa proveedor=%s region=%s etapa=%s", result.provider.value, result.region, stage.value)
            log.finished_at = datetime.now(timezone.utc)
            log.error_count = 1
            log.errors.append(str(exc))
            result.errors.append(f"{stage.value}: {exc}")
            self.audit_logger.record_error(
                result.run_id,
                {
                    "provider": result.provider.value,
                    "region": result.region,
                    "stage": stage.value,
                    "error": str(exc),
                },
            )
            self.audit_logger.save_stage_output(
                result.run_id,
                result.provider.value,
                f"{stage.value}_error",
                {"stage": stage.value, "error": str(exc), "started_at": started.isoformat()},
                region=result.region,
            )
            return None
        finally:
            result.stage_logs.append(log)

    @staticmethod
    def _count_payload(payload: Any) -> int:
        if payload is None:
            return 0
        if isinstance(payload, tuple):
            return sum(len(item) for item in payload if isinstance(item, list))
        if isinstance(payload, list):
            return len(payload)
        if hasattr(payload, "unique_opportunities"):
            return len(payload.unique_opportunities)
        return 1

    def _discover(
        self,
        provider: ProviderName,
        region: str,
        region_prompt: str,
        sources: list[SourceConfig],
        run_id: str,
        dry_run: bool,
    ) -> list[RawProviderResponse]:
        client = self._client_for(provider)
        responses: list[RawProviderResponse] = []

        for source in sources:
            if dry_run or not client.is_configured():
                response = self.discovery.dry_run_response(provider, region, source)
            else:
                messages = self.discovery.build_messages(region_prompt, source, provider_name=provider.value)
                prompt = client.messages_to_prompt(messages)
                provider_response = self.run_discovery(provider.value, prompt, source=source)
                if provider_response.error:
                    raise RuntimeError(provider_response.error)
                response = RawProviderResponse(
                    provider=provider,
                    region=region,
                    source_id=source.id,
                    source_name=source.name,
                    source_url=source.url,
                    prompt_name=region_prompt,
                    content=provider_response.content or "",
                    raw_payload=provider_response.raw_response or {},
                    cost_estimate_usd=provider_response.estimated_cost,
                    metadata={
                        "source_name": source.name,
                        "model": provider_response.model,
                        "input_tokens": provider_response.input_tokens,
                        "output_tokens": provider_response.output_tokens,
                        "discovery": provider_response.metadata,
                        "discovery_mode": "contextual",
                        "prompt_base": "provider_neutral",
                    },
                )

            responses.append(response)
            self.audit_logger.save_raw_response(run_id, response)

        responses.extend(self._discover_open_web(provider, region, run_id, dry_run, client))
        return responses

    def _discover_open_web(
        self,
        provider: ProviderName,
        region: str,
        run_id: str,
        dry_run: bool,
        client: OpenAIClient | PerplexityClient,
    ) -> list[RawProviderResponse]:
        config = self.discovery.load_open_web_config()
        if not config.enabled:
            return []

        region_config = config.regions.get(region)
        if region_config is None:
            logger.info("Open web discovery omitido: region sin configuracion open_web region=%s", region)
            return []

        responses: list[RawProviderResponse] = []
        for theme in config.themes:
            source_id = self._open_web_source_id(region, theme.id)
            source_name = f"Open Web Discovery - {region} - {theme.name}"
            if dry_run or not client.is_configured():
                response = RawProviderResponse(
                    provider=provider,
                    region=region,
                    source_id=source_id,
                    source_name=source_name,
                    source_url=None,
                    run_id=run_id,
                    prompt_name="agents/open_web_discovery_agent.md",
                    content=json.dumps({"items": []}),
                    raw_payload={},
                    metadata={
                        "discovery_mode": "open_web",
                        "theme_id": theme.id,
                        "theme_name": theme.name,
                        "region": region,
                        "dry_run": True,
                    },
                )
            else:
                messages = self.discovery.build_open_web_messages(
                    region=region,
                    theme=theme,
                    region_config=region_config,
                    source_policy=config.official_source_policy,
                    provider_name=provider.value,
                )
                prompt = client.messages_to_prompt(messages)
                provider_response = self.run_discovery(provider.value, prompt, source=None)
                if provider_response.error:
                    raise RuntimeError(provider_response.error)
                response = RawProviderResponse(
                    provider=provider,
                    region=region,
                    source_id=source_id,
                    source_name=source_name,
                    source_url=None,
                    run_id=run_id,
                    prompt_name="agents/open_web_discovery_agent.md",
                    content=provider_response.content or "",
                    raw_payload=provider_response.raw_response or {},
                    cost_estimate_usd=provider_response.estimated_cost,
                    metadata={
                        "discovery_mode": "open_web",
                        "theme_id": theme.id,
                        "theme_name": theme.name,
                        "region": region,
                        "model": provider_response.model,
                        "input_tokens": provider_response.input_tokens,
                        "output_tokens": provider_response.output_tokens,
                        "discovery": provider_response.metadata,
                        "prompt_base": "open_web_discovery",
                    },
                )

            responses.append(response)
            self.audit_logger.save_raw_response(run_id, response)

        return responses

    @staticmethod
    def _open_web_source_id(region: str, theme_id: str) -> str:
        return f"open_web_{region}_{theme_id}"

    def run_discovery(self, provider: str, prompt: str, *, source: SourceConfig | None = None) -> ProviderResponse:
        provider_name = ProviderName(provider)
        if provider_name == ProviderName.PERPLEXITY:
            return self._client_for(provider_name).run_discovery(prompt, source=source)
        if provider_name == ProviderName.OPENAI:
            return self._client_for(provider_name).run_discovery(prompt)
        raise ValueError(f"Unsupported provider: {provider}")

    def _client_for(self, provider: ProviderName) -> OpenAIClient | PerplexityClient:
        if provider == ProviderName.OPENAI:
            return OpenAIClient(self.settings)
        if provider == ProviderName.PERPLEXITY:
            return PerplexityClient(self.settings)
        raise ValueError(f"Proveedor no soportado: {provider}")


ProviderRunner = ProviderPipelineRunner
