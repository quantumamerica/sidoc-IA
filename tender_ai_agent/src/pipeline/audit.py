from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import Settings
from models.schemas import (
    CostReport,
    InsertResult,
    PipelineReport,
    PipelineStage,
    ProviderPipelineResult,
    RawProviderResponse,
    RejectedOpportunity,
    SourceConfig,
)
from utils.json_utils import read_json, write_json


STAGE_FILE_NAMES = {
    PipelineStage.DISCOVERY.value: "discovery_raw.json",
    PipelineStage.IDENTIFICATION.value: "identified_candidates.json",
    PipelineStage.ELIGIBILITY.value: "eligibility_results.json",
    PipelineStage.ENRICHMENT.value: "enriched_opportunities.json",
    PipelineStage.VALIDATION.value: "validation_results.json",
    PipelineStage.CONTENT_QUALITY_VALIDATION.value: "content_quality_validation_results.json",
    PipelineStage.AI_VALIDATION.value: "ai_validation.json",
    PipelineStage.DEDUPLICATION.value: "deduplication_results.json",
    PipelineStage.DB_MAPPING.value: "db_mapped.json",
}


class AuditLogger:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run_dir(self, run_id: str) -> Path:
        return self.settings.output_dir / run_id

    def save_json(self, path: Path, payload: Any) -> Path:
        write_json(path, payload)
        return path

    def save_markdown(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_raw_response(self, run_id: str, response: RawProviderResponse) -> None:
        path = (
            self.settings.output_dir
            / run_id
            / response.provider.value
            / response.region
            / "raw"
            / f"{response.source_id}.json"
        )
        response.raw_response_path = str(path)
        write_json(path, response.model_dump(mode="json"))

    def save_stage_output(self, run_id: str, provider: str, stage: str, payload: Any, region: str | None = None) -> Path:
        filename = STAGE_FILE_NAMES.get(stage, f"{stage}.json")
        path = self.settings.output_dir / run_id / provider
        if region:
            path = path / region
        path = path / filename
        record = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        if path.exists():
            current = read_json(path)
            records = current.get("records", []) if isinstance(current, dict) else []
            records.append(record)
            write_json(path, {"records": records})
        else:
            write_json(path, {"records": [record]})
        return path

    def record_stage_event(self, run_id: str, event: dict[str, Any]) -> None:
        path = self.settings.output_dir / run_id / "stage_events.json"
        record = {"saved_at": datetime.now(timezone.utc).isoformat(), **event}
        if path.exists():
            current = read_json(path)
            events = current if isinstance(current, list) else []
            events.append(record)
            write_json(path, events)
        else:
            write_json(path, [record])

    def record_error(self, run_id: str, error: dict[str, Any]) -> None:
        path = self.settings.output_dir / run_id / "errors.json"
        record = {"saved_at": datetime.now(timezone.utc).isoformat(), **error}
        if path.exists():
            current = read_json(path)
            errors = current if isinstance(current, list) else []
            errors.append(record)
            write_json(path, errors)
        else:
            write_json(path, [record])

    def save_rejections(self, run_id: str, rejections: list[RejectedOpportunity]) -> None:
        path = self.settings.output_dir / run_id / "discarded_opportunities.json"
        write_json(path, [item.model_dump(mode="json") for item in rejections])

    def save_omitted_sources(self, run_id: str, sources: list[SourceConfig]) -> None:
        path = self.settings.output_dir / run_id / "omitted_sources.json"
        write_json(path, [source.model_dump(mode="json") for source in sources])

    def save_run_artifacts(
        self,
        *,
        report: PipelineReport,
        provider_results: list[ProviderPipelineResult],
        sources_loaded: list[SourceConfig],
        omitted_sources: list[SourceConfig],
        discarded: list[RejectedOpportunity],
        final_validated: list[Any],
        final_duplicates: list[Any],
        insert_results: list[InsertResult],
    ) -> None:
        run_dir = self.run_dir(report.run_id)
        inserted_results = [result for result in insert_results if result.inserted]
        db_duplicate_results = [result for result in insert_results if result.duplicate]
        inserted_urls = {result.url for result in inserted_results if result.url}
        inserted_refs = {result.reference for result in inserted_results if result.reference}
        inserted_opportunities = [
            item
            for item in final_validated
            if (item.url and item.url in inserted_urls) or (item.referencia and item.referencia in inserted_refs)
        ]

        self.save_json(run_dir / "run_config.json", self._run_config(report))
        self.save_json(run_dir / "sources_loaded.json", [source.model_dump(mode="json") for source in sources_loaded])
        self.save_omitted_sources(report.run_id, omitted_sources)
        self.save_json(run_dir / "errors.json", self._errors(report))
        self.save_rejections(report.run_id, discarded)
        self.save_json(run_dir / "validated_opportunities.json", [item.model_dump(mode="json") for item in final_validated])
        self.save_json(run_dir / "inserted_opportunities.json", [item.model_dump(mode="json") for item in inserted_opportunities])
        self.save_json(
            run_dir / "duplicates.json",
            {
                "internal_or_cross_provider": [item.model_dump(mode="json") for item in final_duplicates],
                "database": [item.model_dump(mode="json") for item in db_duplicate_results],
            },
        )
        self.save_json(run_dir / "provider_comparison.json", report.comparison)
        report.cost_report = self._cost_report(report)
        self.save_json(run_dir / "cost_report.json", report.cost_report.model_dump(mode="json"))

    def save_report_json(self, report: PipelineReport) -> Path:
        if report.finished_at is None:
            report.finished_at = datetime.now(timezone.utc)
        path = self.settings.output_dir / report.run_id / "execution_report.json"
        write_json(path, report.model_dump(mode="json"))
        return path

    def save_report_markdown(self, report: PipelineReport) -> Path:
        path = self.settings.output_dir / report.run_id / "execution_report.md"
        run_dir = self.run_dir(report.run_id)
        duration = ""
        if report.finished_at:
            duration = str(report.finished_at - report.started_at)

        regions = sorted({item.region for item in report.provider_reports})
        providers = sorted({item.provider.value for item in report.provider_reports})
        sources_total = sum(item.sources_consulted + item.sources_skipped for item in report.provider_reports)
        sources_consulted = sum(item.sources_consulted for item in report.provider_reports)
        candidates_by_provider = Counter()
        candidates_by_region = Counter()
        errors_by_stage = Counter()
        for item in report.provider_reports:
            candidates_by_provider[item.provider.value] += item.candidates
            candidates_by_region[item.region] += item.candidates
        for stage_log in report.stage_logs:
            if stage_log.error_count:
                errors_by_stage[stage_log.stage.value] += stage_log.error_count
        discarded = self._read_optional_json(run_dir / "discarded_opportunities.json", [])
        discarded_by_reason = Counter(
            item.get("motivo_rechazo") or item.get("rejection_reason") or item.get("reason") or "unknown"
            for item in discarded
            if isinstance(item, dict)
        )
        duplicates_payload = self._read_optional_json(run_dir / "duplicates.json", {})
        db_duplicates = duplicates_payload.get("database", []) if isinstance(duplicates_payload, dict) else []
        inserted = self._read_optional_json(run_dir / "inserted_opportunities.json", [])

        lines = [
            "# Execution Report",
            "",
            f"- Run ID: {report.run_id}",
            f"- Fecha/hora de inicio: {report.started_at.isoformat()}",
            f"- Fecha/hora de fin: {report.finished_at.isoformat() if report.finished_at else ''}",
            f"- Duracion: {duration}",
            f"- Dry-run: {report.dry_run}",
            f"- Proveedores ejecutados: {', '.join(providers)}",
            f"- Regiones ejecutadas: {', '.join(regions)}",
            f"- Fuentes totales: {sources_total}",
            f"- Fuentes consultadas: {sources_consulted}",
            f"- Fuentes omitidas por login/captcha: {report.omitted_sources_total}",
            f"- Candidatas detectadas por proveedor: {dict(candidates_by_provider)}",
            f"- Candidatas detectadas por region: {dict(candidates_by_region)}",
            f"- Descartadas por motivo: {dict(discarded_by_reason)}",
            f"- Validadas: {sum(item.valid for item in report.provider_reports)}",
            f"- Duplicadas internas: {sum(item.duplicated for item in report.provider_reports)}",
            f"- Duplicadas contra DB: {len(db_duplicates)}",
            f"- Insertadas en DB: {report.inserted_total}",
            f"- Errores por etapa: {dict(errors_by_stage)}",
            f"- Costo estimado por proveedor/modelo: ver cost_report.json",
            "",
            "## Resumen por modalidad de discovery",
            "",
        ]
        if report.discovery_mode_summary:
            for mode, values in report.discovery_mode_summary.items():
                lines.extend(
                    [
                        f"### {mode}",
                        "",
                        f"- Fuentes consultadas: {values.get('sources_consulted', 0)}",
                        f"- Busquedas por tema: {values.get('theme_runs', 0)}",
                        f"- Respuestas crudas: {values.get('raw_responses', 0)}",
                        f"- Candidatas: {values.get('candidates', 0)}",
                        f"- Elegibles: {values.get('eligible', 0)}",
                        f"- Validadas: {values.get('validated', 0)}",
                        f"- Aprobadas finales: {values.get('approved_final', 0)}",
                        f"- Duplicadas: {values.get('duplicates', 0)}",
                        f"- Descartadas: {values.get('discarded', 0)}",
                        f"- Costo estimado: {values.get('cost_estimate_usd') if values.get('cost_estimate_usd') is not None else 'no disponible'}",
                        f"- Regiones: {', '.join(values.get('regions') or []) if values.get('regions') else 'ninguna'}",
                        f"- Temas: {', '.join(values.get('themes') or []) if values.get('themes') else 'no aplica'}",
                        "",
                    ]
                )
        else:
            lines.extend(["- No hay resumen por modalidad disponible.", ""])
        lines.extend(
            [
            "## Top oportunidades insertadas",
            "",
            ]
        )
        if inserted:
            for item in inserted[:10]:
                lines.append(
                    "- "
                    f"{item.get('titulo_estudio') or item.get('raw_title') or 'Sin titulo'} | "
                    f"{item.get('organismo_contratado') or item.get('contracting_authority') or 'Sin organismo'} | "
                    f"{item.get('country') or item.get('ambito_geografico') or 'Sin pais'} | "
                    f"{item.get('deadline') or item.get('deadline_normalized') or 'Sin deadline'} | "
                    f"{item.get('url') or item.get('official_url') or 'Sin URL'}"
                )
        else:
            lines.append("- No se insertaron oportunidades en esta corrida.")
        lines.extend(
            [
                "",
                "## Oportunidades descartadas",
                "",
            ]
        )
        if discarded:
            for item in discarded[:25]:
                lines.append(
                    "- "
                    f"{item.get('titulo_estudio') or item.get('raw_title') or item.get('title') or 'Sin titulo'} | "
                    f"motivo: {item.get('motivo_rechazo') or item.get('rejection_reason') or item.get('reason') or 'unknown'} | "
                    f"region: {item.get('region') or 'Sin region'} | "
                    f"fuente: {item.get('source_name') or item.get('fuente') or item.get('source_id') or 'Sin fuente'}"
                )
            if len(discarded) > 25:
                lines.append(f"- ... {len(discarded) - 25} descartadas adicionales en discarded_opportunities.json")
        else:
            lines.append("- No se descartaron oportunidades en esta corrida.")
        lines.extend(
            [
                "",
                "## Proveedores",
                "",
            ]
        )
        for provider_report in report.provider_reports:
            lines.extend(
                [
                    f"### {provider_report.provider.value} / {provider_report.region}",
                    "",
                    f"- Fuentes consultadas: {provider_report.sources_consulted}",
                    f"- Fuentes omitidas: {provider_report.sources_skipped}",
                    f"- Respuestas crudas: {provider_report.raw_responses}",
                    f"- Candidatas: {provider_report.candidates}",
                    f"- Elegibles: {provider_report.eligible}",
                    f"- Validadas: {provider_report.valid}",
                    f"- Mapeadas: {provider_report.mapped}",
                    f"- Duplicadas: {provider_report.duplicated}",
                    f"- Descartadas: {provider_report.rejected}",
                    f"- Insertadas: {provider_report.inserted}",
                    "",
                ]
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def save_report(self, report: PipelineReport) -> Path:
        json_path = self.save_report_json(report)
        self.save_report_markdown(report)
        return json_path

    def generate_summary(self, report: PipelineReport) -> dict[str, Any]:
        return {
            "run_id": report.run_id,
            "regions": sorted({item.region for item in report.provider_reports}),
            "providers": sorted({item.provider.value for item in report.provider_reports}),
            "sources_consulted": sum(item.sources_consulted for item in report.provider_reports),
            "sources_omitted": report.omitted_sources_total,
            "candidates": sum(item.candidates for item in report.provider_reports),
            "discarded": report.rejected_total,
            "validated": sum(item.valid for item in report.provider_reports),
            "duplicates": report.duplicated_total,
            "inserted": report.inserted_total,
            "errors": len(report.errors) + sum(len(item.errors) for item in report.provider_reports),
            "discovery_mode_summary": report.discovery_mode_summary,
            "report_path": report.report_path,
        }

    def _run_config(self, report: PipelineReport) -> dict[str, Any]:
        return {
            "run_id": report.run_id,
            "dry_run": report.dry_run,
            "skip_db": report.skip_db,
            "requested_region": report.region,
            "providers": [provider.value for provider in report.providers],
            "started_at": report.started_at.isoformat(),
            "settings": {
                "db_table_name": self.settings.db_table_name,
                "output_dir": str(self.settings.output_dir),
                "log_dir": str(self.settings.log_dir),
                "default_db_estado": self.settings.default_db_estado,
            },
        }

    @staticmethod
    def _errors(report: PipelineReport) -> list[dict[str, Any]]:
        errors = [{"scope": "run", "error": error} for error in report.errors]
        for provider_report in report.provider_reports:
            for error in provider_report.errors:
                errors.append(
                    {
                        "scope": "provider",
                        "provider": provider_report.provider.value,
                        "region": provider_report.region,
                        "error": error,
                    }
                )
        for stage_log in report.stage_logs:
            for error in stage_log.errors:
                errors.append(
                    {
                        "scope": "stage",
                        "provider": stage_log.provider.value if stage_log.provider else None,
                        "region": stage_log.region,
                        "stage": stage_log.stage.value,
                        "error": error,
                    }
                )
        return errors

    @staticmethod
    def _cost_report(report: PipelineReport) -> CostReport:
        by_provider: dict[str, dict[str, Any]] = defaultdict(lambda: {"estimated_usd": None, "regions": []})
        total = 0.0
        has_cost = False
        for provider_report in report.provider_reports:
            entry = by_provider[provider_report.provider.value]
            entry["regions"].append(provider_report.region)
            if provider_report.cost_estimate_usd is not None:
                entry["estimated_usd"] = (entry["estimated_usd"] or 0.0) + provider_report.cost_estimate_usd
                total += provider_report.cost_estimate_usd
                has_cost = True
        return CostReport(
            run_id=report.run_id,
            estimated_usd=total if has_cost else None,
            metadata={"by_provider": dict(by_provider)},
        )

    @staticmethod
    def _read_optional_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        return read_json(path)
