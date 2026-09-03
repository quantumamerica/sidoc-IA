from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from config.db_catalogs import _catalog_key
from config.settings import Settings
from models.schemas import NegocioCatalogConfig, NegocioDefinition

logger = logging.getLogger(__name__)

EXPECTED_SLUGS = (
    "desarrollo_it",
    "agua",
    "gas",
    "generacion",
    "nuevos_negocios",
    "electricidad",
)

# Columnas candidatas para el nombre del negocio en la tabla destino.
NAME_COLUMN_CANDIDATES = ("nombre", "nombre_negocio", "descripcion", "detalle", "negocio")
ID_COLUMN_CANDIDATES = ("id", "negocio_id", "id_negocio")
# Columnas de baja logica: las filas marcadas se ignoran al resolver ids.
DELETED_COLUMN_CANDIDATES = ("borrado", "eliminado", "deleted", "is_deleted")


class NegocioCatalog:
    """Catalogo de unidades de negocio y resolucion de su id en la tabla negocio."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._definitions: list[NegocioDefinition] | None = None
        self._resolved_ids: dict[str, int | None] | None = None
        self._db_rows: list[dict[str, Any]] | None = None

    @property
    def definitions(self) -> list[NegocioDefinition]:
        if self._definitions is None:
            self._definitions = self._load_definitions()
        return self._definitions

    def by_slug(self, slug: str) -> NegocioDefinition | None:
        for definition in self.definitions:
            if definition.slug == slug:
                return definition
        return None

    def slugs(self) -> list[str]:
        return [definition.slug for definition in self.definitions]

    def negocio_id(self, slug: str) -> int | None:
        return self.resolved_ids().get(slug)

    def resolved_ids(self) -> dict[str, int | None]:
        if self._resolved_ids is None:
            self._resolved_ids = self._resolve_ids()
        return self._resolved_ids

    def db_rows(self) -> list[dict[str, Any]]:
        """Filas crudas de la tabla negocio. Lista vacia si no se puede leer."""
        if self._db_rows is None:
            self._db_rows = self._read_db_rows()
        return self._db_rows

    def catalog_summary(self) -> str:
        """Resumen textual del catalogo para inyectar en el prompt de Gemini."""
        lines: list[str] = []
        for definition in sorted(self.definitions, key=lambda item: item.prioridad):
            descripcion = " ".join((definition.descripcion or "").split())
            lines.append(f"- {definition.slug} ({definition.nombre}, prioridad {definition.prioridad}): {descripcion}")
        return "\n".join(lines)

    def _load_definitions(self) -> list[NegocioDefinition]:
        data = self._read_yaml(self.settings.negocios_config_path)
        try:
            config = NegocioCatalogConfig.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Catalogo de negocios invalido en negocios.yaml: {exc}") from exc

        if not config.negocios:
            raise ValueError(
                f"Catalogo de negocios vacio o inexistente: {self.settings.negocios_config_path}"
            )

        definitions: list[NegocioDefinition] = []
        seen_slugs: set[str] = set()
        seen_prioridades: set[int] = set()

        for definition in config.negocios:
            if definition.slug in seen_slugs:
                raise ValueError(f"Negocio duplicado en negocios.yaml: {definition.slug}")
            if definition.prioridad in seen_prioridades:
                raise ValueError(
                    f"Prioridad duplicada en negocios.yaml: {definition.prioridad} (slug {definition.slug})"
                )
            seen_slugs.add(definition.slug)
            seen_prioridades.add(definition.prioridad)
            definitions.append(definition)

        missing = [slug for slug in EXPECTED_SLUGS if slug not in seen_slugs]
        if missing:
            raise ValueError(f"Faltan negocios obligatorios en negocios.yaml: {', '.join(missing)}")

        return definitions

    def _resolve_ids(self) -> dict[str, int | None]:
        resolved: dict[str, int | None] = {}
        pending = [definition for definition in self.definitions if definition.sidoc_id is None]

        for definition in self.definitions:
            if definition.sidoc_id is not None:
                resolved[definition.slug] = definition.sidoc_id

        if not pending:
            return resolved

        by_name = self._db_ids_by_name()
        for definition in pending:
            candidates = [definition.nombre, *definition.nombres_alternativos]
            found: int | None = None
            for candidate in candidates:
                found = by_name.get(_catalog_key(candidate))
                if found is not None:
                    break
            resolved[definition.slug] = found
            if found is None:
                logger.warning(
                    "Negocio sin id resuelto slug=%s nombre=%r; completar sidoc_id en negocios.yaml "
                    "o verificar el nombre en la tabla %s.",
                    definition.slug,
                    definition.nombre,
                    self.settings.negocio_table_name,
                )

        return resolved

    def _db_ids_by_name(self) -> dict[str, int]:
        rows = self.db_rows()
        if not rows:
            return {}

        columns = list(rows[0].keys())
        id_column = self._pick_column(columns, ID_COLUMN_CANDIDATES)
        name_column = self._pick_column(columns, NAME_COLUMN_CANDIDATES)
        if id_column is None or name_column is None:
            logger.warning(
                "No se pudo identificar columnas de id/nombre en la tabla %s; columnas encontradas: %s",
                self.settings.negocio_table_name,
                ", ".join(columns),
            )
            return {}

        deleted_column = self._pick_column(columns, DELETED_COLUMN_CANDIDATES)
        by_name: dict[str, int] = {}
        for row in rows:
            if deleted_column is not None and row.get(deleted_column):
                continue
            name = row.get(name_column)
            identifier = row.get(id_column)
            if name is None or identifier is None:
                continue
            try:
                by_name[_catalog_key(str(name))] = int(identifier)
            except (TypeError, ValueError):
                continue
        return by_name

    def _read_db_rows(self) -> list[dict[str, Any]]:
        if not self.settings.database_url:
            logger.info(
                "DATABASE_URL no configurada: no se pueden resolver ids de negocio desde la tabla %s.",
                self.settings.negocio_table_name,
            )
            return []

        try:
            from sqlalchemy import MetaData, Table, select

            from storage.database import get_engine

            engine = get_engine(self.settings)
            if engine is None:
                return []

            metadata = MetaData()
            table = Table(self.settings.negocio_table_name, metadata, autoload_with=engine)
            with engine.connect() as connection:
                return [dict(row._mapping) for row in connection.execute(select(table)).fetchall()]
        except Exception as exc:
            logger.warning(
                "No se pudo leer la tabla %s para resolver ids de negocio: %s",
                self.settings.negocio_table_name,
                exc,
            )
            return []

    @staticmethod
    def _pick_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
        lowered = {column.lower(): column for column in columns}
        for candidate in candidates:
            if candidate in lowered:
                return lowered[candidate]
        return None

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
