from __future__ import annotations

from typing import Any

from config.db_catalogs import (
    DB_ESTADOS,
    DB_ESTADOS_SEGUIMIENTO,
    DB_FILTROS_GEMINI,
    DB_SELECCIONES,
    DB_SITUACIONES,
    DB_TEMAS,
    normalize_catalog_value,
    normalize_process_type,
)
from config.settings import Settings
from models.schemas import MappedOpportunity, ValidatedOpportunity


class DbMappingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def map(self, opportunities: list[ValidatedOpportunity]) -> list[MappedOpportunity]:
        return [self.map_one(opportunity) for opportunity in opportunities]

    def map_one(self, opportunity: ValidatedOpportunity) -> MappedOpportunity:
        return MappedOpportunity(
            provider=opportunity.provider,
            region=opportunity.region,
            source_id=opportunity.source_id,
            source_name=opportunity.source_name,
            source_url=opportunity.source_url,
            run_id=opportunity.run_id,
            official_url=opportunity.official_url,
            evidence_text=opportunity.evidence_text,
            evidence_urls=opportunity.evidence_urls,
            audit_notes=opportunity.audit_notes,
            id_fuente=opportunity.id_fuente,
            url=opportunity.official_url or opportunity.url,
            fuente=opportunity.fuente,
            organismo_contratado=opportunity.organismo_contratado,
            titulo_estudio=opportunity.titulo_estudio,
            deadline=opportunity.deadline_normalized or opportunity.deadline,
            ambito_geografico=opportunity.ambito_geografico,
            categoria=opportunity.categoria,
            fecha_publicacion=opportunity.publication_date_normalized or opportunity.fecha_publicacion,
            fecha_modificacion=opportunity.modification_date_normalized or opportunity.fecha_modificacion,
            descripcion=opportunity.descripcion,
            idioma=opportunity.idioma,
            tema=normalize_catalog_value(opportunity.tema, DB_TEMAS),
            seleccion=self._setting_catalog("default_db_seleccion", DB_SELECCIONES),
            estado=self._setting_catalog("default_db_estado", DB_ESTADOS, default="Sin Analizar"),
            negocio_id=self.settings.default_negocio_id if self.settings else None,
            referencia=opportunity.referencia,
            controlcomercial=self.settings.default_controlcomercial if self.settings else False,
            cant_palabras_match=opportunity.cant_palabras_match,
            palabras_match=opportunity.palabras_match,
            resumen_descrip=opportunity.resumen_descrip,
            colaborador_id=self.settings.default_colaborador_id if self.settings else None,
            responsable_id=self.settings.default_responsable_id if self.settings else None,
            situacion=self._setting_catalog("default_situacion", DB_SITUACIONES, default="Abierto"),
            tipo_propuesta=normalize_process_type(opportunity.process_type),
            filial_id=self.settings.default_filial_id if self.settings else None,
            filtro_gemini=self._setting_catalog("default_filtro_gemini", DB_FILTROS_GEMINI, default="No analizada"),
            comentario=(
                self._comment(opportunity.run_id)
            ),
            comentarios_personales=self.settings.default_comentarios_personales if self.settings else None,
            estado_seguimiento=self._setting_catalog("default_estado_seguimiento", DB_ESTADOS_SEGUIMIENTO, default="Pendiente"),
        )

    def _comment(self, run_id: str | None) -> str:
        prefix = self.settings.default_comentario_prefix if self.settings else "Cargado automaticamente por tender_ai_agent"
        return f"{prefix} run_id={run_id}" if run_id else prefix

    def _setting_catalog(self, field_name: str, allowed_values: tuple[str, ...], *, default: str | None = None) -> str | None:
        value: Any = getattr(self.settings, field_name, None) if self.settings else None
        return normalize_catalog_value(value, allowed_values, default=default)
