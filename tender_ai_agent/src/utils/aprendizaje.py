"""Ejemplos aprendidos de las senales de SGQ, por negocio.

Los archivos viven en `config/aprendizaje/`:

- `general.yaml`: interruptor `activo` y ejemplos generales (no se tocan desde el loop).
- `<slug>.yaml` (uno por negocio de `config/negocios.yaml`): ejemplos SI/NO que ve el juez
  de negocio y casos de asignacion que ve el Juez 3.

Cada ejemplo tiene `texto` y `origen`. `origen: base` marca los ejemplos escritos a mano;
cualquier otro valor (por ejemplo `licitacion:12345 interes`) es un ejemplo agregado por el
loop. Con `activo: false` solo se usan los de origen `base`: sirve para volver atras de
todo lo aprendido sin tocar codigo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

ORIGEN_BASE = "base"
ARCHIVO_GENERAL = "general.yaml"

TITULO_SI = 'Ejemplos de oportunidades que los consultores de QUANTUM aceptaron (decision "SI"):'
TITULO_NO = 'Ejemplos de oportunidades que los consultores rechazaron (decision "NO"):'
TITULO_ASIGNACION = "Casos que los consultores reasignaron a otra unidad (aprendidos de SGQ):"


@dataclass
class EjemplosNegocio:
    slug: str
    si: list[dict[str, Any]] = field(default_factory=list)
    no: list[dict[str, Any]] = field(default_factory=list)
    asignacion: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Aprendizaje:
    activo: bool = True
    general: EjemplosNegocio = field(default_factory=lambda: EjemplosNegocio("general"))
    negocios: list[EjemplosNegocio] = field(default_factory=list)

    def _filtrar(self, ejemplos: list[dict[str, Any]]) -> list[str]:
        textos = []
        for ejemplo in ejemplos:
            texto = str(ejemplo.get("texto") or "").strip()
            if not texto:
                continue
            if not self.activo and ejemplo.get("origen") != ORIGEN_BASE:
                continue
            textos.append(texto)
        return textos

    def _bloque(self, titulo: str, textos: list[str]) -> str:
        if not textos:
            return ""
        return titulo + "\n" + "\n".join(f"- {texto}" for texto in textos)

    def ejemplos_juez_negocio(self) -> str:
        """Bloques SI y NO para el juez de negocio: primero los de cada negocio, despues los generales."""
        si = [t for negocio in self.negocios for t in self._filtrar(negocio.si)] + self._filtrar(self.general.si)
        no = [t for negocio in self.negocios for t in self._filtrar(negocio.no)] + self._filtrar(self.general.no)
        return "\n\n".join(bloque for bloque in (self._bloque(TITULO_SI, si), self._bloque(TITULO_NO, no)) if bloque)

    def ejemplos_asignacion(self) -> str:
        textos = [t for negocio in self.negocios for t in self._filtrar(negocio.asignacion)]
        return self._bloque(TITULO_ASIGNACION, textos)


def _lista(data: dict[str, Any], clave: str, archivo: Path) -> list[dict[str, Any]]:
    valor = data.get(clave) or []
    if not isinstance(valor, list):
        logger.warning("Aprendizaje: %s en %s no es una lista; se ignora.", clave, archivo.name)
        return []
    return [item if isinstance(item, dict) else {"texto": str(item), "origen": ORIGEN_BASE} for item in valor]


def _leer(archivo: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Aprendizaje: no se pudo leer %s (%s); se ignora.", archivo, exc)
        return {}
    return data if isinstance(data, dict) else {}


def cargar_aprendizaje(config_dir: Path, slugs: list[str] | None = None) -> Aprendizaje:
    """Lee `config/aprendizaje/`. Sin la carpeta devuelve un aprendizaje vacio."""
    carpeta = config_dir / "aprendizaje"
    if not carpeta.is_dir():
        return Aprendizaje()

    general_data = _leer(carpeta / ARCHIVO_GENERAL)
    aprendizaje = Aprendizaje(
        activo=bool(general_data.get("activo", True)),
        general=EjemplosNegocio(
            "general",
            si=_lista(general_data, "ejemplos_si", carpeta / ARCHIVO_GENERAL),
            no=_lista(general_data, "ejemplos_no", carpeta / ARCHIVO_GENERAL),
        ),
    )

    orden = slugs or sorted(p.stem for p in carpeta.glob("*.yaml") if p.name != ARCHIVO_GENERAL)
    for slug in orden:
        archivo = carpeta / f"{slug}.yaml"
        if not archivo.exists():
            continue
        data = _leer(archivo)
        aprendizaje.negocios.append(
            EjemplosNegocio(
                slug,
                si=_lista(data, "ejemplos_si", archivo),
                no=_lista(data, "ejemplos_no", archivo),
                asignacion=_lista(data, "asignacion", archivo),
            )
        )
    return aprendizaje


# Orden en que se muestran los ejemplos al juez (el mismo que tenian en el prompt).
ORDEN_NEGOCIOS = ["electricidad", "desarrollo_it", "nuevos_negocios", "gas", "agua", "generacion"]
