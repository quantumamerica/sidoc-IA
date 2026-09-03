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
from pipeline.negocio_assignment import NegocioAssignmentService
from pipeline.negocio_catalog import NegocioCatalog
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
    run_parser.add_argument(
        "--skip-ai-validation",
        action="store_true",
        help="Desactiva el juez IA (Gemini) para esta corrida.",
    )
    run_parser.add_argument(
        "--ai-threshold",
        type=float,
        help="Sobrescribe el umbral de relevancia del juez IA (0-1) para esta corrida.",
    )
    run_parser.add_argument(
        "--skip-negocio-assignment",
        action="store_true",
        help="Desactiva la asignacion de unidad de negocio para esta corrida.",
    )

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

    negocios_parser = subparsers.add_parser("negocios", help="Gestiona el catalogo de unidades de negocio.")
    negocios_group = negocios_parser.add_mutually_exclusive_group(required=True)
    negocios_group.add_argument(
        "--list",
        action="store_true",
        help="Lista el catalogo y el estado de resolucion de cada negocio_id.",
    )
    negocios_group.add_argument(
        "--classify",
        metavar="TEXTO",
        help="Clasifica un texto suelto y muestra el score por negocio.",
    )
    negocios_parser.add_argument(
        "--use-gemini",
        action="store_true",
        help="Con --classify, consulta a Gemini si las reglas no son concluyentes.",
    )

    return parser


def run_pipeline(args: argparse.Namespace, settings: Settings) -> int:
    region = args.region if args.region else "all"
    providers = [args.provider] if args.provider else settings.default_providers
    dry_run = args.dry_run or settings.dry_run
    max_sources = args.max_sources if args.max_sources is not None else None
    if max_sources is not None and max_sources <= 0:
        raise SystemExit("--max-sources debe ser mayor a 0.")

    settings_overrides: dict[str, object] = {}
    if getattr(args, "skip_ai_validation", False):
        settings_overrides["ai_validation_enabled"] = False
    if getattr(args, "ai_threshold", None) is not None:
        if not 0.0 <= args.ai_threshold <= 1.0:
            raise SystemExit("--ai-threshold debe estar entre 0 y 1.")
        settings_overrides["ai_validation_threshold"] = args.ai_threshold
    if getattr(args, "skip_negocio_assignment", False):
        settings_overrides["negocio_assignment_enabled"] = False
    if settings_overrides:
        settings = settings.model_copy(update=settings_overrides)

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


def run_negocios_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        catalog = NegocioCatalog(settings)
        catalog.definitions
    except Exception as exc:
        print(f"No se pudo cargar el catalogo de negocios: {exc}")
        return 1

    if args.classify:
        return _classify_negocio(args, settings, catalog)
    return _list_negocios(settings, catalog)


def _list_negocios(settings: Settings, catalog: NegocioCatalog) -> int:
    db_rows = catalog.db_rows()
    resolved = catalog.resolved_ids()

    print("Catalogo (config/negocios.yaml)\n")
    rows = [
        {
            "slug": definition.slug,
            "nombre": definition.nombre,
            "prioridad": definition.prioridad,
            "sidoc_id_yaml": definition.sidoc_id if definition.sidoc_id is not None else "",
            "negocio_id": resolved.get(definition.slug) if resolved.get(definition.slug) is not None else "NO RESUELTO",
            "origen": _negocio_id_origin(definition.sidoc_id, resolved.get(definition.slug)),
        }
        for definition in sorted(catalog.definitions, key=lambda item: item.prioridad)
    ]
    _print_table(rows, ["slug", "nombre", "prioridad", "sidoc_id_yaml", "negocio_id", "origen"])

    print(f"\nTabla '{settings.negocio_table_name}' en la base\n")
    if not db_rows:
        if not settings.database_url:
            print("DATABASE_URL no configurada: no se pueden resolver ids desde la base.")
        else:
            print(f"No se pudieron leer filas de la tabla '{settings.negocio_table_name}'. Ver logs.")
    else:
        columns = list(db_rows[0].keys())
        _print_table([{column: row.get(column) for column in columns} for row in db_rows], columns)
        print(f"\nTotal: {len(db_rows)} fila(s)")

    unresolved = [definition for definition in catalog.definitions if resolved.get(definition.slug) is None]
    if unresolved:
        print("\nNegocios sin id resuelto:")
        for definition in unresolved:
            sugerencia = _suggest_db_match(definition.nombre, db_rows)
            print(f"  - {definition.slug} ({definition.nombre}): {sugerencia}")
        print(
            "\nCompletar 'sidoc_id' en config/negocios.yaml, o ajustar 'nombre'/'nombres_alternativos'"
            f" para que coincidan con la tabla '{settings.negocio_table_name}'."
        )
    else:
        print("\nTodos los negocios tienen negocio_id resuelto.")

    return 0


def _negocio_id_origin(sidoc_id: int | None, resolved_id: int | None) -> str:
    if sidoc_id is not None:
        return "yaml"
    if resolved_id is not None:
        return "lookup por nombre"
    return "sin resolver"


def _suggest_db_match(nombre: str, db_rows: list[dict[str, object]]) -> str:
    if not db_rows:
        return "sin filas de la base para comparar"

    from difflib import SequenceMatcher

    columns = list(db_rows[0].keys())
    name_column = next(
        (column for column in columns if column.lower() in {"nombre", "nombre_negocio", "descripcion", "detalle"}),
        None,
    )
    if name_column is None:
        return f"no se identifico columna de nombre; columnas: {', '.join(columns)}"

    id_column = next((column for column in columns if column.lower() in {"id", "negocio_id", "id_negocio"}), None)
    best_row: dict[str, object] | None = None
    best_ratio = 0.0
    for row in db_rows:
        candidate = str(row.get(name_column) or "")
        ratio = SequenceMatcher(None, nombre.casefold(), candidate.casefold()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_row = row

    if best_row is None:
        return "sin coincidencias"
    candidate_id = best_row.get(id_column) if id_column else "?"
    return f"candidato mas parecido: id={candidate_id} nombre={best_row.get(name_column)!r} (similitud {best_ratio:.2f})"


def _classify_negocio(args: argparse.Namespace, settings: Settings, catalog: NegocioCatalog) -> int:
    service = NegocioAssignmentService(settings, catalog=catalog)
    scores, decision = service.classify_text(args.classify, use_gemini=args.use_gemini)

    print(f"Texto: {args.classify}\n")
    rows = [
        {
            "slug": item.slug,
            "score": item.score,
            "raw": item.raw_score,
            "prioridad": item.prioridad,
            "dominantes": ", ".join(item.dominant_hits[:4]),
            "fuertes": ", ".join(item.strong_hits[:4]),
            "debiles": ", ".join(item.weak_hits[:4]),
            "excluyentes": ", ".join(item.excluding_hits[:4]),
        }
        for item in scores
    ]
    _print_table(rows, ["slug", "score", "raw", "prioridad", "dominantes", "fuertes", "debiles", "excluyentes"])

    print(
        f"\nDecision: {decision.slug or 'sin_asignar'}"
        f" | negocio_id: {decision.negocio_id if decision.negocio_id is not None else 'NO RESUELTO'}"
        f" | metodo: {decision.method} ({decision.detail})"
        f" | confianza: {decision.confidence if decision.confidence is not None else 'n/d'}"
    )
    print(f"Motivo: {decision.reason}")
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
    if args.command == "negocios":
        return run_negocios_command(args, settings)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
