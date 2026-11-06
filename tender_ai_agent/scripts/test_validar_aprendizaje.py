from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validar_aprendizaje import validar  # noqa: E402

BASE = """# comentario
ejemplos_si:
  - texto: ejemplo base
    origen: base
ejemplos_no: []
asignacion: []
"""


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    (repo / "tender_ai_agent/config/aprendizaje").mkdir(parents=True)
    (repo / "tender_ai_agent/config/aprendizaje/gas.yaml").write_text(BASE, encoding="utf-8")
    (repo / "tender_ai_agent/config/aprendizaje/agua.yaml").write_text(BASE, encoding="utf-8")
    (repo / "tender_ai_agent/config/aprendizaje/general.yaml").write_text("activo: true\n", encoding="utf-8")
    (repo / "tender_ai_agent/main.py").write_text("print('hola')\n", encoding="utf-8")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "aprendizaje/gas/x"], check=True)
    return repo


def _probar(cambios: dict[str, str]) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(Path(tmp))
        for ruta, contenido in cambios.items():
            (repo / ruta).write_text(contenido, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"], check=True)
        return validar(repo, "main", "HEAD")


GAS = "tender_ai_agent/config/aprendizaje/gas.yaml"
BUENO = BASE.replace(
    "ejemplos_no: []",
    "ejemplos_no:\n  - texto: Estudio de impacto ambiental de un gasoducto\n    origen: licitacion:123 descartada fuera_rubro",
)


def test_valido() -> None:
    assert _probar({GAS: BUENO}) == []


def test_rechazos() -> None:
    assert any("fuera de lo permitido" in e for e in _probar({GAS: BUENO, "tender_ai_agent/main.py": "x\n"}))
    assert any("no permitido" in e for e in _probar({"tender_ai_agent/config/aprendizaje/general.yaml": "activo: false\n"}))
    assert any("un solo negocio" in e for e in _probar({GAS: BUENO, "tender_ai_agent/config/aprendizaje/agua.yaml": BUENO}))
    assert any("origen base" in e for e in _probar({GAS: BASE.replace("ejemplo base", "otro")}))
    assert any("no cita la licitacion" in e for e in _probar({GAS: BUENO.replace("licitacion:123", "yo")}))
    tres = BASE.replace(
        "ejemplos_no: []",
        "ejemplos_no:\n" + "".join(f"  - texto: n{i}\n    origen: licitacion:{i} x\n" for i in range(3)),
    )
    assert any("altas" in e for e in _probar({GAS: tres}))
    assert any("`umbral`" in e for e in _probar({GAS: BUENO + "umbral: 0.5\n"}))


if __name__ == "__main__":
    test_valido()
    test_rechazos()
    print("OK")
