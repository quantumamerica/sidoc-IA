from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for ruta in (PROJECT_ROOT / "src", PROJECT_ROOT):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

from utils.aprendizaje import ORDEN_NEGOCIOS, TITULO_NO, TITULO_SI, cargar_aprendizaje  # noqa: E402


def test_config_del_repo() -> None:
    aprendizaje = cargar_aprendizaje(PROJECT_ROOT / "config", ORDEN_NEGOCIOS)
    assert aprendizaje.activo
    assert [n.slug for n in aprendizaje.negocios] == ORDEN_NEGOCIOS
    texto = aprendizaje.ejemplos_juez_negocio()
    assert texto.startswith(TITULO_SI) and TITULO_NO in texto
    assert "GERC" in texto and "Osinergmin" in texto
    # Todos los negocios del catalogo tienen su archivo.
    import yaml

    catalogo = yaml.safe_load((PROJECT_ROOT / "config" / "negocios.yaml").read_text(encoding="utf-8"))
    slugs = {n["slug"] for n in catalogo["negocios"]}
    assert slugs == set(ORDEN_NEGOCIOS), slugs
    assert aprendizaje.ejemplos_asignacion() == ""


def test_interruptor_y_origen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        carpeta = Path(tmp) / "aprendizaje"
        carpeta.mkdir()
        (carpeta / "general.yaml").write_text("activo: false\n", encoding="utf-8")
        (carpeta / "gas.yaml").write_text(
            "ejemplos_si:\n"
            "  - texto: base gas\n    origen: base\n"
            "  - texto: aprendido gas\n    origen: licitacion:1 interes\n"
            "asignacion:\n  - texto: aprendido asignacion\n    origen: licitacion:2 derivada\n",
            encoding="utf-8",
        )
        apagado = cargar_aprendizaje(Path(tmp), ["gas"])
        assert "base gas" in apagado.ejemplos_juez_negocio()
        assert "aprendido" not in apagado.ejemplos_juez_negocio()
        assert apagado.ejemplos_asignacion() == ""

        (carpeta / "general.yaml").write_text("activo: true\n", encoding="utf-8")
        prendido = cargar_aprendizaje(Path(tmp), ["gas"])
        assert "aprendido gas" in prendido.ejemplos_juez_negocio()
        assert "aprendido asignacion" in prendido.ejemplos_asignacion()
        assert TITULO_NO not in prendido.ejemplos_juez_negocio()


def test_sin_carpeta() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        assert cargar_aprendizaje(Path(tmp)).ejemplos_juez_negocio() == ""


if __name__ == "__main__":
    test_config_del_repo()
    test_interruptor_y_origen()
    test_sin_carpeta()
    print("OK")
