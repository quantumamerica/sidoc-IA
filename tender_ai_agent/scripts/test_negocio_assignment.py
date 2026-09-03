from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config.settings import Settings
from models.schemas import DB_COLUMNS, DbMappedOpportunity, ProviderName, ValidatedOpportunity
from pipeline.db_mapping import DbMappingService
from pipeline.negocio_assignment import NegocioAssignmentService, NegocioRuleScorer
from pipeline.negocio_catalog import NegocioCatalog

INTERNAL_NEGOCIO_FIELDS = (
    "negocio_slug",
    "negocio_nombre",
    "negocio_confidence",
    "negocio_assignment_method",
    "negocio_scores",
)

# Casos que la capa determinista debe resolver sin consultar a Gemini.
CASES: list[tuple[str, str]] = [
    ("Estudio tarifario de agua potable y saneamiento", "agua"),
    ("Green hydrogen feasibility study and regulatory framework", "gas"),
    ("Consultoria para diseno de subastas de energia y potencia en el mercado mayorista", "generacion"),
    ("Desarrollo de plataforma GIS para empresa distribuidora electrica", "desarrollo_it"),
    ("Estrategia de transicion energetica y penetracion de renovables", "nuevos_negocios"),
    ("Revision tarifaria quinquenal de distribucion electrica", "electricidad"),
    ("Software de liquidacion del mercado mayorista electrico", "desarrollo_it"),
    ("Licitacion de generacion solar fotovoltaica", "nuevos_negocios"),
    # Variantes con tildes y en otros idiomas: el matching normaliza el texto.
    ("Estudio tarifario de agua potable y saneamiento básico", "agua"),
    ("Estudo de viabilidade de hidrogênio verde para transição energética", "gas"),
    ("Wholesale electricity market design and capacity auction advisory", "generacion"),
    ("Consultoria para revisión de la estructura tarifaria de transmisión eléctrica", "electricidad"),
]


def build_settings() -> Settings:
    """Settings minimo: no depende del .env ni de la base de datos."""
    return Settings(
        project_root=PROJECT_ROOT,
        output_dir=PROJECT_ROOT / "outputs",
        log_dir=PROJECT_ROOT / "logs",
    )


def check_db_payload_isolation() -> list[str]:
    """Los campos de auditoria del asignador no deben viajar al INSERT."""
    errors: list[str] = []

    opportunity = ValidatedOpportunity(
        provider=ProviderName.OPENAI,
        region="latam",
        source_id="demo",
        raw_title="Estudio tarifario de agua potable",
        official_url="https://example.org/tender/1",
    )
    opportunity.negocio_id = 4
    opportunity.negocio_slug = "agua"
    opportunity.negocio_nombre = "Agua"
    opportunity.negocio_confidence = 0.69
    opportunity.negocio_assignment_method = "rules"
    opportunity.negocio_scores = {"agua": 0.69}

    mapped = DbMappedOpportunity.from_validated(opportunity)
    payload = mapped.to_db_dict(exclude_none=False)

    extra_columns = [column for column in payload if column not in DB_COLUMNS]
    if extra_columns:
        errors.append(f"to_db_dict() devolvio columnas fuera de DB_COLUMNS: {extra_columns}")

    leaked = [field_name for field_name in INTERNAL_NEGOCIO_FIELDS if field_name in payload]
    if leaked:
        errors.append(f"Campos internos filtrados al payload de INSERT: {leaked}")

    if payload.get("negocio_id") != 4:
        errors.append(f"negocio_id no llego al payload de INSERT: {payload.get('negocio_id')!r}")

    metadata = mapped.internal_metadata(exclude_none=False)
    missing = [field_name for field_name in INTERNAL_NEGOCIO_FIELDS if field_name not in metadata]
    if missing:
        errors.append(f"Campos internos ausentes en internal_metadata(): {missing}")

    return errors


def build_opportunity(title: str) -> ValidatedOpportunity:
    return ValidatedOpportunity(
        provider=ProviderName.OPENAI,
        region="latam",
        source_id="demo",
        raw_title=title,
        official_url=f"https://example.org/tender/{abs(hash(title)) % 10000}",
    )


def check_stage_flow(settings: Settings, catalog: NegocioCatalog) -> list[str]:
    """Flujo completo de la etapa sin Gemini (GOOGLE_API_KEY ausente) y su mapeo a la base."""
    errors: list[str] = []

    # settings sin google_api_key: la etapa debe resolver por reglas y no romper.
    service = NegocioAssignmentService(settings, catalog=catalog)
    if service.client.is_configured():
        errors.append("El settings de prueba no deberia tener GOOGLE_API_KEY configurada.")

    opportunities = [build_opportunity(text) for text, _ in CASES[:8]]
    assigned = service.assign(opportunities)

    if len(assigned) != len(opportunities):
        errors.append(f"assign() cambio la cantidad de oportunidades: {len(assigned)} != {len(opportunities)}")

    for opportunity, (text, expected) in zip(assigned, CASES[:8]):
        if opportunity.negocio_slug != expected:
            errors.append(f"assign() asigno {opportunity.negocio_slug!r} en vez de {expected!r} para: {text}")
        # Sin DATABASE_URL el catalogo no puede resolver ids: se espera el mismo valor que el catalogo.
        expected_id = catalog.negocio_id(expected)
        if opportunity.negocio_id != expected_id:
            errors.append(
                f"assign() escribio negocio_id={opportunity.negocio_id!r} en vez de {expected_id!r} para: {text}"
            )
        if opportunity.negocio_assignment_method != "rules":
            errors.append(
                f"assign() uso metodo {opportunity.negocio_assignment_method!r} sin Gemini para: {text}"
            )
        if not any(note.startswith("[Negocio]") for note in opportunity.audit_notes):
            errors.append(f"assign() no dejo nota de auditoria para: {text}")
        if not opportunity.negocio_scores:
            errors.append(f"assign() no guardo scores para: {text}")

    mapped = DbMappingService(settings).map(assigned)
    for item, opportunity in zip(mapped, assigned):
        if item.negocio_id != opportunity.negocio_id:
            errors.append(
                f"db_mapping no propago negocio_id: {item.negocio_id!r} != {opportunity.negocio_id!r}"
            )

    return errors


def main() -> int:
    settings = build_settings()
    catalog = NegocioCatalog(settings)
    definitions = catalog.definitions
    scorer = NegocioRuleScorer(definitions)

    print(f"Negocios cargados: {', '.join(definition.slug for definition in definitions)}")
    print(
        f"Umbrales: strong_threshold={settings.negocio_rules_strong_threshold} "
        f"margin={settings.negocio_rules_margin}\n"
    )

    failures: list[str] = []
    for text, expected in CASES:
        scores = scorer.score_all(text)
        outcome = scorer.decide(
            scores,
            strong_threshold=settings.negocio_rules_strong_threshold,
            margin=settings.negocio_rules_margin,
        )
        actual = outcome.slug if outcome else None
        detail = outcome.detail if outcome else "no concluyente (iria a Gemini)"
        status = "OK  " if actual == expected else "FALLA"
        top = scores[0]
        print(f"{status} {text}")
        print(f"       esperado={expected} obtenido={actual} via={detail} top_score={top.score}")
        if actual != expected:
            failures.append(text)
            ranking = ", ".join(f"{item.slug}={item.score}" for item in scores if item.raw_score > 0)
            print(f"       ranking: {ranking or 'sin senales'}")

    print()
    payload_errors = check_db_payload_isolation()
    if payload_errors:
        print("Aislamiento del payload de INSERT: FALLA")
        for error in payload_errors:
            print(f"  - {error}")
    else:
        print("Aislamiento del payload de INSERT: OK (solo negocio_id llega a la tabla)")

    stage_errors = check_stage_flow(settings, catalog)
    if stage_errors:
        print("Flujo de la etapa sin Gemini: FALLA")
        for error in stage_errors:
            print(f"  - {error}")
    else:
        print("Flujo de la etapa sin Gemini: OK (asigna por reglas y propaga a db_mapping)")

    print()
    if failures or payload_errors or stage_errors:
        if failures:
            print(f"FALLARON {len(failures)} de {len(CASES)} casos de clasificacion:")
            for text in failures:
                print(f"  - {text}")
        return 1

    print(f"Todos los casos pasaron ({len(CASES)}/{len(CASES)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
