from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config.settings import Settings
from models.schemas import MappedOpportunity, PipelineReport, ProviderName, ProviderPipelineResult
from pipeline.audit import AuditLogger
from pipeline.comparison import ProviderComparisonService
from pipeline.persistence import PersistenceService
from pipeline.provider_runner import ProviderPipelineRunner
from utils.source_loader import SourceLoader

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.source_loader = SourceLoader(settings)
        self.audit_logger = AuditLogger(settings)
        self.provider_runner = ProviderPipelineRunner(settings, self.audit_logger)
        self.comparison = ProviderComparisonService()
        self.persistence = PersistenceService(settings)

    def run(
        self,
        *,
        region: str,
        providers: list[str],
        compare_providers: bool,
        dry_run: bool,
        skip_db: bool = False,
        max_sources: int | None = None,
    ) -> PipelineReport:
        if region == "all":
            return self.run_all(
                providers=providers,
                compare_providers=compare_providers,
                dry_run=dry_run,
                skip_db=skip_db,
                max_sources=max_sources,
            )
        return self.run_region(
            region=region,
            providers=providers,
            compare_providers=compare_providers,
            dry_run=dry_run,
            skip_db=skip_db,
            max_sources=max_sources,
        )

    def run_all(
        self,
        *,
        providers: list[str],
        compare_providers: bool = True,
        dry_run: bool = False,
        skip_db: bool = False,
        max_sources: int | None = None,
    ) -> PipelineReport:
        regions = self.source_loader.load_regions()
        return self._run_regions(
            selected_regions=list(regions.keys()),
            requested_region="all",
            providers=providers,
            compare_providers=compare_providers,
            dry_run=dry_run,
            skip_db=skip_db,
            max_sources=max_sources,
        )

    def run_region(
        self,
        *,
        region: str,
        providers: list[str],
        compare_providers: bool = True,
        dry_run: bool = False,
        skip_db: bool = False,
        max_sources: int | None = None,
    ) -> PipelineReport:
        return self._run_regions(
            selected_regions=[region],
            requested_region=region,
            providers=providers,
            compare_providers=compare_providers,
            dry_run=dry_run,
            skip_db=skip_db,
            max_sources=max_sources,
        )

    def run_provider_region(
        self,
        *,
        run_id: str,
        provider: ProviderName,
        region: str,
        sources: list,
        omitted_sources: list,
        dry_run: bool,
    ) -> ProviderPipelineResult:
        regions = self.source_loader.load_regions()
        region_config = regions[region]
        return self.provider_runner.run(
            run_id=run_id,
            provider=provider,
            region=region,
            region_prompt=region_config.discovery_prompt,
            sources=sources,
            omitted_sources=omitted_sources,
            dry_run=dry_run,
        )

    def _run_regions(
        self,
        *,
        selected_regions: list[str],
        requested_region: str,
        providers: list[str],
        compare_providers: bool,
        dry_run: bool,
        skip_db: bool,
        max_sources: int | None,
    ) -> PipelineReport:
        run_id = self._new_run_id()
        provider_names = [ProviderName(provider) for provider in providers]
        report = PipelineReport(
            run_id=run_id,
            started_at=datetime.now(timezone.utc),
            dry_run=dry_run,
            skip_db=skip_db,
            region=requested_region,
            providers=provider_names,
        )

        regions = self.source_loader.load_regions()
        sources_loaded = self.source_loader.load_sources()
        provider_results: list[ProviderPipelineResult] = []
        all_discarded = []
        all_omitted_sources = []

        for region_key in selected_regions:
            region_config = regions.get(region_key)
            if region_config is None:
                report.errors.append(f"Region no configurada: {region_key}")
                continue

            enabled_sources = self.source_loader.list_sources(region=region_key, enabled_only=True, skip_restricted=False)
            sources = [source for source in enabled_sources if not source.is_restricted]
            if max_sources is not None:
                sources = sources[:max_sources]
            omitted_sources = [source for source in enabled_sources if source.is_restricted]
            all_omitted_sources.extend(omitted_sources)
            if not sources:
                logger.info("No hay fuentes activas para region %s", region_key)
                continue

            for provider in provider_names:
                try:
                    provider_result = self.run_provider_region(
                        run_id=run_id,
                        provider=provider,
                        region=region_key,
                        sources=sources,
                        omitted_sources=omitted_sources,
                        dry_run=dry_run,
                    )
                    provider_results.append(provider_result)
                    report.provider_reports.append(provider_result.report)
                    report.stage_logs.extend(provider_result.stage_logs)
                    all_discarded.extend(provider_result.discarded)
                except Exception as exc:
                    logger.exception("Error region=%s proveedor=%s", region_key, provider.value)
                    report.errors.append(f"{region_key}/{provider.value}: {exc}")
                    self.audit_logger.record_error(
                        run_id,
                        {
                            "provider": provider.value,
                            "region": region_key,
                            "stage": "provider_region",
                            "error": str(exc),
                        },
                    )

        self.audit_logger.save_omitted_sources(run_id, all_omitted_sources)
        self.audit_logger.save_rejections(run_id, all_discarded)

        mapped_by_provider = self._mapped_by_provider(provider_results)
        merged_mapped: list[MappedOpportunity] = []
        if compare_providers or len(provider_names) > 1:
            comparison_result, merged_mapped = self.comparison.compare_opportunities(
                run_id=run_id,
                openai_items=mapped_by_provider.get(ProviderName.OPENAI, []),
                perplexity_items=mapped_by_provider.get(ProviderName.PERPLEXITY, []),
            )
            report.comparison = comparison_result.model_dump(mode="json")
            self.audit_logger.save_json(
                self.audit_logger.run_dir(run_id) / "provider_comparison.json",
                comparison_result.model_dump(mode="json"),
            )
        else:
            merged_mapped = [item for result in provider_results for item in result.mapped]

        final_unique, final_duplicates = self.comparison.final_deduplicate(merged_mapped)
        self.audit_logger.save_json(
            self.audit_logger.run_dir(run_id) / "duplicates.json",
            {
                "internal_or_cross_provider": [item.model_dump(mode="json") for item in final_duplicates],
                "database": [],
            },
        )

        inserted = self.persistence.persist(final_unique, dry_run=dry_run, run_id=run_id, skip_db=skip_db)
        if report.provider_reports:
            report.provider_reports[-1].inserted = inserted

        report.approved_total = len(final_unique)
        report.inserted_total = inserted
        report.rejected_total = len(all_discarded)
        report.discarded_opportunities_summary = self._discarded_summary(all_discarded)
        report.discovery_mode_summary = self._discovery_mode_summary(provider_results, final_unique)
        report.duplicated_total = sum(item.duplicated for item in report.provider_reports) + len(final_duplicates)
        report.omitted_sources_total = len(all_omitted_sources)
        report.finished_at = datetime.now(timezone.utc)
        json_report_path = self.audit_logger.run_dir(run_id) / "execution_report.json"
        report.report_path = str(json_report_path)
        self.audit_logger.save_run_artifacts(
            report=report,
            provider_results=provider_results,
            sources_loaded=sources_loaded,
            omitted_sources=all_omitted_sources,
            discarded=all_discarded,
            final_validated=final_unique,
            final_duplicates=final_duplicates,
            insert_results=self.persistence.last_insert_results,
        )
        self.audit_logger.save_report(report)
        return report

    @staticmethod
    def _mapped_by_provider(results: list[ProviderPipelineResult]) -> dict[ProviderName, list[MappedOpportunity]]:
        grouped: dict[ProviderName, list[MappedOpportunity]] = {}
        for result in results:
            grouped.setdefault(result.provider, []).extend(result.mapped)
        return grouped

    @staticmethod
    def _discarded_summary(discarded: list) -> list[dict[str, object]]:
        return [
            {
                "title": item.titulo_estudio or item.raw_title or item.title or "Sin titulo",
                "region": item.region,
                "source_id": item.source_id or item.id_fuente,
                "source_name": item.source_name or item.fuente,
                "stage": item.stage.value if hasattr(item.stage, "value") else str(item.stage),
                "reason": item.motivo_rechazo
                or (item.reason.value if hasattr(item.reason, "value") else str(item.reason)),
                "deadline": item.deadline.isoformat() if hasattr(item.deadline, "isoformat") else item.deadline,
                "url": item.url or item.official_url,
            }
            for item in discarded
        ]

    @classmethod
    def _discovery_mode_summary(
        cls,
        provider_results: list[ProviderPipelineResult],
        final_unique: list[MappedOpportunity],
    ) -> dict[str, dict[str, object]]:
        summary = {
            "contextual": cls._empty_discovery_mode_summary(),
            "open_web": cls._empty_discovery_mode_summary(),
        }
        for result in provider_results:
            for raw in result.raw_results:
                mode = cls._discovery_mode(raw)
                item = summary.setdefault(mode, cls._empty_discovery_mode_summary())
                item["raw_responses"] += 1
                item["cost_estimate_usd"] += raw.cost_estimate_usd or 0
                if mode == "contextual":
                    item["sources_consulted"] += 1
                elif mode == "open_web":
                    item["theme_runs"] += 1
                    theme_id = raw.metadata.get("theme_id")
                    if theme_id:
                        item["themes"].add(theme_id)
                item["regions"].add(result.region)
                item["providers"].add(result.provider.value)

            for candidate in result.candidates:
                summary.setdefault(cls._discovery_mode(candidate), cls._empty_discovery_mode_summary())["candidates"] += 1
            for candidate in result.eligible:
                summary.setdefault(cls._discovery_mode(candidate), cls._empty_discovery_mode_summary())["eligible"] += 1
            for candidate in result.enriched:
                summary.setdefault(cls._discovery_mode(candidate), cls._empty_discovery_mode_summary())["enriched"] += 1
            for candidate in result.validated:
                summary.setdefault(cls._discovery_mode(candidate), cls._empty_discovery_mode_summary())["validated"] += 1
            for candidate in result.mapped:
                summary.setdefault(cls._discovery_mode(candidate), cls._empty_discovery_mode_summary())["mapped"] += 1
            for candidate in result.duplicates:
                summary.setdefault(cls._discovery_mode(candidate), cls._empty_discovery_mode_summary())["duplicates"] += 1
            for candidate in result.discarded:
                summary.setdefault(cls._discovery_mode(candidate), cls._empty_discovery_mode_summary())["discarded"] += 1

        for item in final_unique:
            summary.setdefault(cls._discovery_mode(item), cls._empty_discovery_mode_summary())["approved_final"] += 1

        return {
            mode: {
                **values,
                "regions": sorted(values["regions"]),
                "providers": sorted(values["providers"]),
                "themes": sorted(values["themes"]),
                "cost_estimate_usd": round(values["cost_estimate_usd"], 6) if values["cost_estimate_usd"] else None,
            }
            for mode, values in summary.items()
        }

    @staticmethod
    def _empty_discovery_mode_summary() -> dict[str, object]:
        return {
            "sources_consulted": 0,
            "theme_runs": 0,
            "raw_responses": 0,
            "candidates": 0,
            "eligible": 0,
            "enriched": 0,
            "validated": 0,
            "mapped": 0,
            "approved_final": 0,
            "duplicates": 0,
            "discarded": 0,
            "cost_estimate_usd": 0.0,
            "regions": set(),
            "providers": set(),
            "themes": set(),
        }

    @staticmethod
    def _discovery_mode(item) -> str:
        metadata = getattr(item, "metadata", None) or {}
        mode = metadata.get("discovery_mode")
        if mode:
            return str(mode)
        raw_metadata = metadata.get("raw_response_metadata") or {}
        mode = raw_metadata.get("discovery_mode")
        if mode:
            return str(mode)
        source_id = getattr(item, "source_id", None) or getattr(item, "id_fuente", None) or ""
        if str(source_id).startswith("open_web_") or str(source_id).startswith("open_web:"):
            return "open_web"
        return "contextual"

    def _new_run_id(self) -> str:
        candidate = datetime.now(timezone.utc).replace(microsecond=0)
        while True:
            run_id = candidate.strftime("%Y%m%d_%H%M%S")
            if not (self.settings.output_dir / run_id).exists():
                return run_id
            candidate = candidate + timedelta(seconds=1)
