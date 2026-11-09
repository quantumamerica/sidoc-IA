"""Regla de obras/EPC de Elegibilidad: no descartar consultorias sobre obras (corrida 20261107_000002)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pipeline.eligibility import is_works_title

# (titulo, es obra?)
CASES = [
    # Consultorias que la regla vieja descartaba porque decian "obra" o "construction" en algun lado.
    ("Revisión y revalidación de las prioridades de las obras de expansión del Sistema de Transmisión en Alta Tensión de Argentina", False),
    ("Licitación Pública 0009/2026 - Servicios de consultoría de la obra APROVECHAMIENTO HIDROELÉCTRICO LA BARRANCOSA Y LEAT", False),
    ("Consultoría por los Servicio de supervisión técnica del proyecto de perforación de pozos geotérmicos en campo geotérmico Chinameca", False),
    ("RFP: Update of the (i) technical studies and bidding documents for irrigation and hydropower", False),
    ("Reconstruction needs assessment of the power sector", False),
    ("Future Smart Metering Programme for AMP8 and Beyond", False),
    ("Construction supervision consultant for the 220 kV transmission line", False),
    # Obras y EPC de verdad.
    ("Construction of 132kV substation at Kigali", True),
    ("EPC contract for 50 MW solar PV plant", True),
    ("Obras civiles para la línea de transmisión 220 kV", True),
    ("Construcción de la subestación Norte 500 kV", True),
]


def main() -> int:
    failures = [
        f"{title[:70]!r}: esperado {'obra' if expected else 'no obra'}"
        for title, expected in CASES
        if is_works_title(title) != expected
    ]
    if failures:
        print(f"FALLA elegibilidad obras ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"OK elegibilidad obras ({len(CASES)} titulos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
