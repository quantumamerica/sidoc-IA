"""Copias del mismo aviso con otra URL, titulo o sin plazo (casos de la corrida 20261105_000002)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config.settings import Settings
from models.schemas import MappedOpportunity, ProviderName, PipelineStage, RejectedOpportunity, RejectionReason, ValidatedOpportunity
from pipeline.ai_validation import JUDGE_SCHEMA, AiBusinessValidationService
from pipeline.comparison import ProviderComparisonService
from pipeline.db_mapping import DbMappingService
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.similarity import looks_like_same_opportunity

NOV19 = date(2026, 11, 19)
NOV23 = date(2026, 11, 23)

# (titulo A, plazo A, organismo A, url A, titulo B, plazo B, organismo B, url B, misma?)
CASES = [
    (
        "COST OF SERVICE AND RATE CONSULTING SERVICES", NOV23, "New York Power Authority",
        "https://www.lightrfp.com/marketplace/bid/NYPA-6653/cost-of-service-and-rate-consulting-services",
        "Cost of Service and Rate Consulting Services", NOV23, "Power Authority of New York",
        "https://www.nyscr.ny.gov/Ads/Search?Skip=75", True,
    ),
    (
        "City of Corona Electric Utility Battery Energy Storage System Feasibility Study (RFP 27-017AG)", None,
        "City of Corona", "https://www.highergov.com/sl/contract-opportunity/ca-city-of-corona-electric-utility-battery-75021971/",
        "CITY OF CORONA ELECTRIC UTILITY BATTERY ENERGY STORAGE SYSTEM FEASIBILITY STUDY", NOV19,
        "City of Corona Utilities Department", "https://www.planetbids.com/portal/portal.cfm?CompanyID=39497", True,
    ),
    (
        "RFP-529-2026 - Electricity consulting and related services for the Region of Durham", NOV19, "Region of Durham",
        "https://durham.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/44328106",
        "Electricity consulting and related services for the Region of Durham", NOV19, "Region of Durham",
        "https://www.cleat.ai/government/contracts/electricity-consulting-and-r", True,
    ),
    (
        "Renewable Energy Generation and Access Increase Project: Preparation of an Energy Sector Investment Program for the Marshall Islands",
        None, "World Bank", "https://www.developmentaid.org/tenders/view/1702059/renewable-energy",
        "Preparation of an Energy Sector Investment Program for the Marshall Islands", NOV23,
        "Government of the Republic of the Marshall Islands", "https://www.tenderhive.com/tenders/WB-OP00459459", True,
    ),
    (
        "Consultoría para el fortalecimiento de la ...", None, "IADB",
        "https://www.developmentaid.org/tenders/view/1692782/consultoria-para-el-fortalecimiento-de-la-metodologia-de-la-planificacion-de-la-expansion-del-sistem",
        "B260040 - Consultoría para el fortalecimiento de la metodología de la planificación de la expansión del sistema eléctrico costarricense considerando alta participación de generación renovable variable",
        date(2026, 8, 11), "IDB", "https://beo-procurement.iadb.org/en/node/214880", True,
    ),
    # Distintas: mismo tema generico en otra ciudad, o plazos que no se tocan.
    (
        "Cost of Service and Rate Study", NOV19, "City of Columbia (MO)", "https://a.example/1",
        "Cost of Service and Rate Study", None, "Town of Minnedosa", "https://b.example/2", False,
    ),
    (
        "Electric Cost of Service and Rate Study", date(2026, 11, 9), "City of Columbia",
        "https://a.example/1", "Electric Cost of Service and Rate Study", date(2026, 12, 20), "City of Columbia",
        "https://b.example/2", False,
    ),
    (
        "CM3592 - Consultancy", date(2026, 11, 9), "Yorkshire Water", "https://a.example/1",
        "CM3600 - Consultancy", date(2026, 11, 9), "Yorkshire Water", "https://b.example/2", False,
    ),
    (
        "Utility Rate Study - Water, Sewer and Solid Waste Disposal", None, "Town of X", "https://a.example/1",
        "Electric Utility Rate Study and Financial Planning Consultant", None, "Town of X", "https://b.example/2", False,
    ),
]


def mapped(title: str, deadline: date | None, authority: str | None, url: str) -> MappedOpportunity:
    return MappedOpportunity(titulo_estudio=title, deadline=deadline, organismo_contratado=authority, url=url)


def build_settings() -> Settings:
    return Settings(project_root=PROJECT_ROOT, output_dir=PROJECT_ROOT / "outputs", log_dir=PROJECT_ROOT / "logs")


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.provider = ProviderName.ANTHROPIC

    def is_configured(self) -> bool:
        return True

    def run_agent(self, *args, **kwargs):
        from clients.base import ProviderResponse

        return ProviderResponse(provider="anthropic", model="claude-opus-5-5", parsed_json=self.payload)


def main() -> int:
    failures: list[str] = []

    for title_a, dl_a, org_a, url_a, title_b, dl_b, org_b, url_b, expected in CASES:
        got = looks_like_same_opportunity(
            title_a, title_b, deadline_a=dl_a, deadline_b=dl_b, authority_a=org_a, authority_b=org_b, url_a=url_a, url_b=url_b
        )
        if got != expected:
            failures.append(f"{title_a[:50]!r} vs {title_b[:50]!r}: esperado {expected}, dio {got}")

    # Dentro de la corrida: Corona por highergov (sin plazo) y procuretap (con plazo) queda una, la que trae plazo.
    corona_a = mapped(CASES[1][0], None, "City of Corona", "https://www.highergov.com/sl/corona")
    corona_b = mapped(CASES[1][0], NOV19, "City of Corona", "https://procuretap.com/bid/323880")
    unique, duplicates = ProviderComparisonService().final_deduplicate([corona_a, corona_b])
    if len(unique) != 1 or unique[0].deadline != NOV19 or len(duplicates) != 1:
        failures.append(f"Corona x2 en la corrida: quedaron {len(unique)} y la elegida tiene plazo {unique[0].deadline if unique else None}")

    # Copia sin plazo de un aviso que en la fuente oficial figura vencido.
    official = RejectedOpportunity(
        normalized_title=CASES[4][4],
        organismo_contratado="IDB",
        official_url=CASES[4][7],
        deadline_normalized=date(2026, 8, 11),
        stage=PipelineStage.AI_VALIDATION,
        reason=RejectionReason.DEADLINE_EXPIRED,
    )
    copy = mapped(CASES[4][0], None, "IADB", CASES[4][3])
    other = mapped("CM3592 - Consultancy for regulatory price review", date(2026, 11, 9), "Yorkshire Water", "https://x/1")
    kept, dropped = PipelineOrchestrator._drop_copies_of_expired([copy, other], [official])
    if len(kept) != 1 or kept[0] is not other or len(dropped) != 1:
        failures.append("La copia de developmentaid del B260040 vencido no se descarto (o se descarto otra).")
    elif dropped[0].reason != RejectionReason.DEADLINE_EXPIRED.value:
        failures.append(f"La copia vencida se descarto con motivo {dropped[0].reason}.")

    # El juez informa el plazo que leyo: si ya paso, la descarta como vencida y guarda la fecha.
    if "deadline_found" not in JUDGE_SCHEMA["required"]:
        failures.append("El esquema del juez no pide deadline_found.")
    service = AiBusinessValidationService(
        build_settings(),
        client=FakeClient(
            {
                "relevance_score": 0.9,
                "is_consulting": True,
                "is_works_or_equipment": False,
                "is_tender_notice": True,
                "decision": "NO",
                "reason": "El plazo REOI (2026-08-11) es anterior a la fecha actual.",
                "deadline_found": "2026-08-11",
            }
        ),
    )
    approved, rejected = service.validate([ValidatedOpportunity(provider=ProviderName.PERPLEXITY, titulo_estudio=CASES[4][4], url=CASES[4][7])])
    if approved or not rejected or rejected[0].reason != RejectionReason.DEADLINE_EXPIRED.value:
        failures.append(f"Juez con plazo vencido: motivo {rejected[0].reason if rejected else 'aprobada'}")
    elif rejected[0].deadline_normalized != date(2026, 8, 11):
        failures.append("Juez con plazo vencido: no se guardo la fecha que leyo.")

    # Marca de revision visible en ia_motivo_juez cuando el Juez 3 duda.
    item = ValidatedOpportunity(
        provider=ProviderName.PERPLEXITY,
        titulo_estudio="Municipal Financial Consulting and Utility Rate Advisory Services",
        metadata={
            "ai_judge": {"model": "claude-opus-5-5", "score": 0.75, "reason": "Asesoria tarifaria municipal."},
            "negocio_judge": {"method": "claude", "confidence": 0.45, "needs_review": True},
        },
    )
    motivo = DbMappingService(build_settings()).map_one(item).ia_motivo_juez or ""
    if not motivo.startswith("[Revisar negocio: confianza 0.45]"):
        failures.append(f"ia_motivo_juez sin marca de revision: {motivo!r}")

    if failures:
        print(f"FALLA duplicados ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"OK duplicados ({len(CASES)} pares + corrida, vencidas, juez y revision)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
