"""Filtro de idioma en la elegibilidad: solo pasan avisos en espanol, ingles, portugues o frances.

    python scripts/test_idioma.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from models.schemas import OpportunityCandidate, ProviderName, RejectionReason
from pipeline.eligibility import EligibilityService
from pipeline.search_results_reader import READER_SCHEMA
from utils.language import guess_language, normalize_language

# (titulo, idioma declarado, descripcion, pasa, idioma que queda guardado)
CASES: list[tuple[str, str | None, str | None, bool, str | None]] = [
    # Declarado por el buscador.
    ("Utility Rate Study and Financial Planning Consultant", "en", None, True, "en"),
    ("Estudio tarifario de distribucion electrica", "Spanish", None, True, "es"),
    ("Estudo de viabilidade de hidrogenio verde", "Portuguese (Brazil)", None, True, "pt"),
    ("Etude tarifaire de l'electricite", "fr-FR", None, True, "fr"),
    ("Mehrsprachig", "es/en", None, True, "en"),
    # El caso real del 25-sep-2026.
    ("Consulting, gruner Wasserstoff/Wertschopfungskette von Batterien | Ausschreibungsmeldung | Sudafrika", "de", None, False, None),
    ("Servizi di consulenza per la regolazione tariffaria", "italiano", None, False, None),
    # Otro alfabeto: se descarta aunque el buscador diga ingles.
    ("Консультационные услуги по тарифному регулированию", "en", None, False, None),
    ("خدمات استشارية لتنظيم قطاع الكهرباء", None, None, False, None),
    # Sin idioma declarado: se estima del texto.
    ("Ausschreibung: Beratung zur Regulierung und Dienstleistungen fur die Energieversorgung", None, None, False, None),
    ("Affidamento del servizio di consulenza per la gara della regolazione delle tariffe", None, None, False, None),
    ("Consultoria para la revision de la estructura tarifaria del servicio electrico", None, None, True, "es"),
    ("Request for proposals for the provision of consulting services to the regulator", None, None, True, "en"),
    ("Recrutement d'un cabinet pour l'etude des tarifs de l'electricite et des services", None, None, True, "fr"),
    # Texto corto o ambiguo: no alcanza para descartar.
    ("AR-T1371-P003", None, None, True, None),
    ("Grid Code Modernisation", None, None, True, None),
]


def candidate(title: str, language: str | None, description: str | None) -> OpportunityCandidate:
    return OpportunityCandidate(
        provider=ProviderName.PERPLEXITY,
        region="latam",
        source_id="demo",
        raw_title=title,
        normalized_title=title,
        language=language,
        description_raw=description,
        official_url="https://example.org/tender/1",
        evidence_text=title,
    )


def main() -> int:
    service = EligibilityService(deadline_grace_days=1)
    failures: list[str] = []
    for title, language, description, should_pass, stored in CASES:
        item = candidate(title, language, description)
        result = service.evaluate(item)
        passed = result.is_eligible
        if passed != should_pass:
            failures.append(f"{title!r} (declarado {language!r}): paso={passed}, esperado={should_pass}, motivo={result.reason}")
            continue
        if not passed and result.reason != RejectionReason.LANGUAGE_NOT_ALLOWED:
            failures.append(f"{title!r}: descartado por {result.reason} y no por idioma")
        if passed and stored is not None and item.idioma != stored:
            failures.append(f"{title!r}: idioma guardado {item.idioma!r}, esperado {stored!r}")

    # Idiomas configurables: con ALLOWED_LANGUAGES=es,en el frances queda afuera.
    narrow = EligibilityService(allowed_languages=["es", "en"])
    if narrow.evaluate(candidate("Etude tarifaire de l'electricite", "fr", None)).is_eligible:
        failures.append("Con allowed_languages=['es','en'] paso un aviso en frances.")

    if normalize_language("English") != "en" or normalize_language("es-AR") != "es" or normalize_language("xx") is not None:
        failures.append("normalize_language no reconoce nombres o codigos regionales.")
    if guess_language("hola") is not None:
        failures.append("guess_language decidio con una sola palabra.")

    if "language" not in READER_SCHEMA["properties"]["items"]["items"]["required"]:
        failures.append("La segunda lectura no exige el idioma de cada aviso.")

    if failures:
        print(f"FALLA idioma ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"OK idioma ({len(CASES)} casos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
