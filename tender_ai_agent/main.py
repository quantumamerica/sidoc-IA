from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.settings import Settings, load_settings
from pipeline.orchestrator import PipelineOrchestrator
from storage.database import get_engine, test_connection
from storage.repositories import OpportunityRepository
from utils.logging_config import configure_logging
from utils.source_loader import SourceLoader

VALID_RUN_REGIONS = [
    "latam",
    "africa",
    "eastern_europe",
    "oceania",
    "usa_cities",
    "global_cities",
    "multilaterals",
    "europe_global",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tender-ai-agent",
        description="Busqueda automatica de oportunidades comerciales y licitaciones.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Ejecuta el pipeline de busqueda.")
    run_scope = run_parser.add_mutually_exclusive_group()
    run_scope.add_argument("--all", action="store_true", help="Ejecuta todas las regiones configuradas.")
    run_scope.add_argument("--region", choices=VALID_RUN_REGIONS, help="Ejecuta una region especifica.")
    run_parser.add_argument(
        "--provider",
        choices=["openai", "perplexity"],
        help="Ejecuta un unico proveedor. Por defecto ejecuta todos los configurados.",
    )
    run_parser.add_argument(
        "--compare-providers",
        action="store_true",
        help="Incluye comparacion explicita entre resultados de proveedores.",
    )
    run_parser.add_argument("--dry-run", action="store_true", help="No inserta registros en base de datos.")
    run_parser.add_argument("--no-db", action="store_true", help="Ejecuta pipeline sin insertar en base de datos.")
    run_parser.add_argument("--max-sources", type=int, help="Limita cantidad de fuentes consultadas por region.")

    sources_parser = subparsers.add_parser("sources", help="Gestiona fuentes configuradas.")
    sources_parser.add_argument("--list", action="store_true", help="Lista las fuentes configuradas.")
    sources_parser.add_argument("--region", help="Filtra fuentes por region.")
    sources_parser.add_argument("--enabled-only", action="store_true", help="Muestra solo fuentes habilitadas.")

    report_parser = subparsers.add_parser("report", help="Consulta reportes de ejecucion.")
    report_group = report_parser.add_mutually_exclusive_group(required=True)
    report_group.add_argument("--last-run", action="store_true", help="Muestra el ultimo reporte generado.")
    report_group.add_argument("--run-id", help="Muestra el reporte de un run_id especifico.")

    db_parser = subparsers.add_parser("db", help="Operaciones de base de datos.")
    db_group = db_parser.add_mutually_exclusive_group(required=True)
    db_group.add_argument("--test", action="store_true", help="Prueba conexion y existencia de tabla destino.")
    db_group.add_argument("--recent", type=int, metavar="DAYS", help="Lista registros recientes de la tabla destino.")

    prompts_parser = subparsers.add_parser("prompts", help="Gestiona prompts editables.")
    prompts_parser.add_argument("--list", action="store_true", required=True, help="Lista prompts Markdown disponibles.")

    return parser


def run_pipeline(args: argparse.Namespace, settings: Settings) -> int:
    region = args.region if args.region else "all"
    providers = [args.provider] if args.provider else settings.default_providers
    dry_run = args.dry_run or settings.dry_run
    max_sources = args.max_sources if args.max_sources is not None else None
    if max_sources is not None and max_sources <= 0:
        raise SystemExit("--max-sources debe ser mayor a 0.")

    orchestrator = PipelineOrchestrator(settings=settings)
    report = orchestrator.run(
        region=region,
        providers=providers,
        compare_providers=args.compare_providers,
        dry_run=dry_run,
        skip_db=args.no_db,
        max_sources=max_sources,
    )

    print_run_summary(report)
    return 0


def print_run_summary(report) -> None:
    sources_consulted = sum(item.sources_consulted for item in report.provider_reports)
    candidates = sum(item.candidates for item in report.provider_reports)
    validated = sum(item.valid for item in report.provider_reports)
    errors = len(report.errors) + sum(len(item.errors) for item in report.provider_reports)
    cost_values = [item.cost_estimate_usd for item in report.provider_reports if item.cost_estimate_usd is not None]
    estimated_cost = sum(cost_values) if cost_values else None
    regions = sorted({item.region for item in report.provider_reports})

    print(f"Run ID: {report.run_id}")
    print(f"Regiones ejecutadas: {', '.join(regions) if regions else 'ninguna'}")
    print(f"Fuentes consultadas: {sources_consulted}")
    print(f"Fuentes omitidas: {report.omitted_sources_total}")
    print(f"Candidatas encontradas: {candidates}")
    print(f"Descartadas: {report.rejected_total}")
    print(f"Validadas: {validated}")
    print(f"Duplicadas: {report.duplicated_total}")
    print(f"Insertadas en DB: {report.inserted_total}")
    print(f"Errores: {errors}")
    print(f"Costo estimado: {estimated_cost if estimated_cost is not None else 'no disponible'}")
    if report.discovery_mode_summary:
        print("Resumen por modalidad:")
        for mode, values in report.discovery_mode_summary.items():
            cost = values.get("cost_estimate_usd")
            print(
                f"  - {mode}: "
                f"fuentes={values.get('sources_consulted', 0)}, "
                f"busquedas_tema={values.get('theme_runs', 0)}, "
                f"raw={values.get('raw_responses', 0)}, "
                f"candidatas={values.get('candidates', 0)}, "
                f"elegibles={values.get('eligible', 0)}, "
                f"validadas={values.get('validated', 0)}, "
                f"aprobadas_finales={values.get('approved_final', 0)}, "
                f"duplicadas={values.get('duplicates', 0)}, "
                f"descartadas={values.get('discarded', 0)}, "
                f"costo={cost if cost is not None else 'no disponible'}"
            )
    print(f"Ruta del reporte: {report.report_path or ''}")


def _format_bool_unknown(value: bool | str) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def _print_table(rows: list[dict[str, object]], columns: list[str]) -> None:
    if not rows:
        print("No hay fuentes para los filtros indicados.")
        return

    widths = {
        column: max(len(column), *(len(str(row.get(column, "") or "")) for row in rows))
        for column in columns
    }
    header = " | ".join(column.ljust(widths[column]) for column in columns)
    separator = "-+-".join("-" * widths[column] for column in columns)
    print(header)
    print(separator)
    for row in rows:
        print(" | ".join(str(row.get(column, "") or "").ljust(widths[column]) for column in columns))


def list_sources(args: argparse.Namespace, settings: Settings) -> int:
    loader = SourceLoader(settings=settings)
    sources = loader.list_sources(region=args.region, enabled_only=args.enabled_only)
    rows = [
        {
            "id": source.id,
            "name": source.name,
            "region": source.region,
            "country": source.country or "",
            "priority": source.priority.value,
            "enabled": source.enabled,
            "login": _format_bool_unknown(source.requires_login),
            "captcha": _format_bool_unknown(source.has_captcha),
            "type": source.source_type.value,
            "strategy": source.search_strategy.value,
            "url": source.url or "",
        }
        for source in sources
    ]
    _print_table(
        rows,
        ["id", "name", "region", "country", "priority", "enabled", "login", "captcha", "type", "strategy", "url"],
    )
    print(f"\nTotal: {len(rows)} fuente(s)")
    return 0


def show_report(args: argparse.Namespace, settings: Settings) -> int:
    if args.run_id:
        report_path = settings.output_dir / args.run_id / "execution_report.json"
        if not report_path.exists():
            print(f"No existe reporte para run_id={args.run_id}.")
            return 1
        print(report_path.read_text(encoding="utf-8"))
        return 0

    reports = sorted(settings.output_dir.glob("*/execution_report.json"), reverse=True)
    if not reports:
        print("No hay reportes generados todavia.")
        return 0

    print(reports[0].read_text(encoding="utf-8"))
    return 0


def run_db_command(args: argparse.Namespace, settings: Settings) -> int:
    if args.test:
        ok, message = test_connection(settings)
        print(message)
        return 0 if ok else 1

    engine = get_engine(settings)
    if engine is None:
        print("DATABASE_URL no configurada.")
        return 1

    try:
        repository = OpportunityRepository(engine, settings.db_table_name)
        rows = repository.get_recent(args.recent)
    except Exception as exc:
        print(f"No se pudo consultar la DB: {exc}")
        return 1

    print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    print(f"\nTotal: {len(rows)} registro(s)")
    return 0


def list_prompts(settings: Settings) -> int:
    prompts = sorted(settings.prompts_dir.glob("**/*.md"))
    rows = [
        {
            "path": str(path.relative_to(settings.project_root)),
            "group": path.parent.name,
        }
        for path in prompts
    ]
    _print_table(rows, ["group", "path"])
    print(f"\nTotal: {len(rows)} prompt(s)")
    return 0


def main() -> int:
    settings = load_settings(PROJECT_ROOT)
    configure_logging(settings)

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        return run_pipeline(args, settings)
    if args.command == "sources":
        return list_sources(args, settings)
    if args.command == "report":
        return show_report(args, settings)
    if args.command == "db":
        return run_db_command(args, settings)
    if args.command == "prompts":
        return list_prompts(settings)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
