"""Valida que un PR del loop de senales solo toque lo permitido.

Lo corre el workflow `.github/workflows/aprendizaje.yml` para las ramas `aprendizaje/*`,
siempre con la version de este archivo que esta en `main` (un PR no puede cambiar sus
propias reglas). Si algo no cumple, sale con codigo 1 y el PR no se mergea.

    python scripts/validar_aprendizaje.py --repo . --base origin/main --head HEAD

Reglas (fase F2: solo ejemplos):
- Solo cambia `tender_ai_agent/config/aprendizaje/<slug>.yaml` de UN negocio. Nunca
  `general.yaml`, codigo, prompts, workflows ni otra config.
- En ese archivo solo cambian `ejemplos_si`, `ejemplos_no` y `asignacion`.
- Los ejemplos con `origen: base` no se tocan.
- Cada ejemplo nuevo tiene `texto` (hasta 300 caracteres) y un `origen` que cita la licitacion.
- Por PR: hasta 2 altas y 2 bajas por lista.
- En total, el loop puede tener hasta 3 SI, 3 NO y 6 casos de asignacion propios por negocio.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

CARPETA = "tender_ai_agent/config/aprendizaje/"
SLUGS = {"electricidad", "gas", "agua", "generacion", "nuevos_negocios", "desarrollo_it"}
LISTAS = {"ejemplos_si": 3, "ejemplos_no": 3, "asignacion": 6}
MAX_ALTAS = 2
MAX_BAJAS = 2
MAX_TEXTO = 300
ORIGEN_BASE = "base"
ORIGEN_LOOP = re.compile(r"^licitacion:\d+\b")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _yaml_en(repo: Path, ref: str, ruta: str) -> dict:
    try:
        texto = _git(repo, "show", f"{ref}:{ruta}")
    except subprocess.CalledProcessError:
        return {}
    data = yaml.safe_load(texto) or {}
    return data if isinstance(data, dict) else {}


def _clave(item: object) -> tuple[str, str]:
    if isinstance(item, dict):
        return (str(item.get("texto") or "").strip(), str(item.get("origen") or "").strip())
    return (str(item).strip(), ORIGEN_BASE)


def validar(repo: Path, base: str, head: str) -> list[str]:
    errores: list[str] = []
    cambiados = [r for r in _git(repo, "diff", "--name-only", f"{base}...{head}").splitlines() if r.strip()]
    if not cambiados:
        return ["El PR no cambia nada."]

    punto_de_partida = _git(repo, "merge-base", base, head).strip()
    negocios = []
    for ruta in cambiados:
        if not (ruta.startswith(CARPETA) and ruta.endswith(".yaml")):
            errores.append(f"Archivo fuera de lo permitido: {ruta}")
            continue
        slug = ruta[len(CARPETA):-len(".yaml")]
        if slug not in SLUGS:
            errores.append(f"Archivo de aprendizaje no permitido: {ruta}")
            continue
        negocios.append((slug, ruta))
    if len(negocios) > 1:
        errores.append("Un PR del loop toca un solo negocio: " + ", ".join(s for s, _ in negocios))

    for slug, ruta in negocios:
        antes = _yaml_en(repo, punto_de_partida, ruta)
        try:
            despues = yaml.safe_load(_git(repo, "show", f"{head}:{ruta}")) or {}
        except (subprocess.CalledProcessError, yaml.YAMLError) as exc:
            errores.append(f"{slug}: no se puede leer el YAML ({exc}).")
            continue
        if not isinstance(despues, dict):
            errores.append(f"{slug}: el YAML no es un mapa.")
            continue

        otras = (set(antes) | set(despues)) - set(LISTAS)
        for clave in sorted(otras):
            if antes.get(clave) != despues.get(clave):
                errores.append(f"{slug}: cambia `{clave}`, que el loop no puede tocar.")

        for lista, tope in LISTAS.items():
            viejos = [_clave(i) for i in (antes.get(lista) or [])]
            nuevos_items = despues.get(lista) or []
            if not isinstance(nuevos_items, list):
                errores.append(f"{slug}: `{lista}` no es una lista.")
                continue
            nuevos = [_clave(i) for i in nuevos_items]
            base_antes = sorted(k for k in viejos if k[1] == ORIGEN_BASE)
            base_despues = sorted(k for k in nuevos if k[1] == ORIGEN_BASE)
            if base_antes != base_despues:
                errores.append(f"{slug}: cambia ejemplos de origen base en `{lista}`.")
            altas = [k for k in nuevos if k not in viejos]
            bajas = [k for k in viejos if k not in nuevos]
            if len(altas) > MAX_ALTAS:
                errores.append(f"{slug}: {len(altas)} altas en `{lista}` (maximo {MAX_ALTAS}).")
            if len(bajas) > MAX_BAJAS:
                errores.append(f"{slug}: {len(bajas)} bajas en `{lista}` (maximo {MAX_BAJAS}).")
            propios = [k for k in nuevos if k[1] != ORIGEN_BASE]
            if len(propios) > tope:
                errores.append(f"{slug}: {len(propios)} ejemplos propios en `{lista}` (maximo {tope}).")
            for item, (texto, origen) in zip(nuevos_items, nuevos):
                if (texto, origen) not in altas:
                    continue
                if not isinstance(item, dict) or set(item) - {"texto", "origen"}:
                    errores.append(f"{slug}: un ejemplo nuevo de `{lista}` no tiene la forma texto/origen.")
                if not texto or len(texto) > MAX_TEXTO:
                    errores.append(f"{slug}: un ejemplo nuevo de `{lista}` esta vacio o pasa {MAX_TEXTO} caracteres.")
                if not ORIGEN_LOOP.match(origen):
                    errores.append(f"{slug}: el ejemplo nuevo '{texto[:40]}' no cita la licitacion en `origen`.")
    return errores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    errores = validar(Path(args.repo), args.base, args.head)
    if errores:
        print("El PR NO cumple las reglas del loop de senales:")
        for error in errores:
            print(f"- {error}")
        return 1
    print("El PR cumple las reglas del loop de senales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
