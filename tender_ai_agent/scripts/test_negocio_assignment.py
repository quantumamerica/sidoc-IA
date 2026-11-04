from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from clients.base import ProviderResponse
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

# Casos que el fallback por palabras clave resuelve si el Juez 3 (Claude) no responde.
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


class FakeJudge:
    """Cliente de Claude simulado: devuelve el slug que se le indique y guarda el prompt."""

    provider = ProviderName.ANTHROPIC
    model = "claude-opus-5-5"

    def __init__(self, reply: dict | None = None, error: str | None = None, configured: bool = True) -> None:
        self.reply = reply
        self.error = error
        self.configured = configured
        self.prompts: list[str] = []
        self.schemas: list[dict] = []

    def is_configured(self) -> bool:
        return self.configured

    def run_agent(self, prompt, response_format="json", stage=None, json_schema=None):
        self.prompts.append(prompt)
        self.schemas.append(json_schema or {})
        if self.error:
            return ProviderResponse(provider=self.provider, model=self.model, error=self.error)
        return ProviderResponse(
            provider=self.provider,
            model=self.model,
            content=json.dumps(self.reply),
            parsed_json=self.reply,
            metadata={"served_model": self.model},
        )


def check_stage_flow(settings: Settings, catalog: NegocioCatalog) -> list[str]:
    """Juez 3: Claude decide siempre, aunque haya palabras dominantes de otro negocio."""
    errors: list[str] = []

    # El caso de Islas Marshall del 4-nov: "hydrogen" (de otro aviso) mandaba la oportunidad a Gas.
    opportunity = build_opportunity("Energy Act Implementation and Regulatory support - Marshall Islands")
    opportunity.description_raw = "Legal advice in the green hydrogen sector (GIZ Mauritania)."
    opportunity.metadata = {"ai_judge": {"reason": "Apoyo regulatorio para implementar la Ley de Energia."}}
    judge = FakeJudge({"negocio_slug": "electricidad", "confidence": 0.85, "alternativa_slug": None, "reason": "Regulacion."})
    service = NegocioAssignmentService(settings, client=judge, catalog=catalog)
    [assigned] = service.assign([opportunity])

    if assigned.negocio_slug != "electricidad":
        errors.append(f"El Juez 3 no mando: quedo {assigned.negocio_slug!r} en vez de 'electricidad'.")
    if assigned.negocio_assignment_method != "claude":
        errors.append(f"Metodo {assigned.negocio_assignment_method!r} en vez de 'claude'.")
    if assigned.negocio_id != catalog.negocio_id("electricidad"):
        errors.append(f"negocio_id {assigned.negocio_id!r} no corresponde a electricidad.")
    if len(judge.prompts) != 1:
        errors.append(f"Se esperaba 1 consulta al Juez 3 y hubo {len(judge.prompts)}.")
    else:
        prompt = judge.prompts[0]
        if "Apoyo regulatorio para implementar" not in prompt:
            errors.append("El prompt del Juez 3 no incluye el motivo del juez de negocio.")
        if "Candidatos sugeridos" in prompt or "{{" in prompt:
            errors.append("El prompt del Juez 3 trae pistas de palabras clave o variables sin completar.")
        enum = judge.schemas[0].get("properties", {}).get("negocio_slug", {}).get("enum")
        if sorted(enum or []) != sorted(definition.slug for definition in catalog.definitions):
            errors.append(f"El esquema del Juez 3 no limita el slug al catalogo: {enum!r}")
    if assigned.requires_human_review:
        errors.append("Una asignacion del Juez 3 no deberia quedar marcada para revision.")
    if not any(note.startswith("[Negocio]") and "Juez 3" in note for note in assigned.audit_notes):
        errors.append("No quedo nota de auditoria del Juez 3.")

    # Slug fuera del catalogo o error de la API: fallback por palabras clave, marcado para revision.
    for label, fake in (
        ("error", FakeJudge(error="timeout")),
        ("slug_invalido", FakeJudge({"negocio_slug": "mineria", "confidence": 0.9, "alternativa_slug": None, "reason": "x"})),
        ("sin_api_key", FakeJudge(configured=False)),
    ):
        opportunity = build_opportunity("Estudio tarifario de agua potable y saneamiento")
        [assigned] = NegocioAssignmentService(settings, client=fake, catalog=catalog).assign([opportunity])
        if assigned.negocio_assignment_method != "fallback":
            errors.append(f"{label}: metodo {assigned.negocio_assignment_method!r} en vez de 'fallback'.")
        if assigned.negocio_slug != "agua":
            errors.append(f"{label}: el fallback asigno {assigned.negocio_slug!r} en vez de 'agua'.")
        if not assigned.requires_human_review:
            errors.append(f"{label}: el fallback no marco la oportunidad para revision humana.")
        if label == "sin_api_key" and fake.prompts:
            errors.append("sin_api_key: no deberia consultar al Juez 3.")

    mapped = DbMappingService(settings).map([assigned])
    if mapped[0].negocio_id != assigned.negocio_id:
        errors.append(f"db_mapping no propago negocio_id: {mapped[0].negocio_id!r} != {assigned.negocio_id!r}")

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
        detail = outcome.detail if outcome else "no concluyente"
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
        print("Flujo de la etapa (Juez 3 y fallback): FALLA")
        for error in stage_errors:
            print(f"  - {error}")
    else:
        print("Flujo de la etapa: OK (decide el Juez 3; el fallback marca para revision y propaga a db_mapping)")

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
