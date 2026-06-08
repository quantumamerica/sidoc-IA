from __future__ import annotations

import unicodedata
from typing import Any


DB_TEMAS = (
    "Análisis MEM",
    "Apoyo en la Gestión",
    "Apoyo Legal",
    "Apoyo Regulatorio",
    "Arbitraje",
    "Benchmarking",
    "Cálculo Costos Explotación",
    "Cálculo Tarifario",
    "Cálculo Tasa Capital",
    "Cálculo VNR",
    "Calidad de Servicio",
    "Campaña Caracterización de Cargas",
    "Capacitación in Company",
    "Cogeneración y Autogeneración",
    "Contabilidad Regulatoria",
    "Det. Valor Empresa",
    "Energías Renovables",
    "Estructura Tarifaria",
    "Estudio de factibilidad",
    "Estudio de prospectiva",
)

DB_SELECCIONES = (
    "Seleccionada por SIDOC",
    "No seleccionada",
    "Seleccionada Manualmente",
    "Seleccionada por Agente IA",
)

DB_FILTROS_GEMINI = (
    "Seleccionada por Gemini",
    "Descartada por Gemini",
    "No analizada",
)

DB_ESTADOS = (
    "Propuesta Aceptada",
    "Rechazada",
    "Sin Analizar",
    "Esperando Respuesta",
)

DB_TIPOS_PROPUESTA = (
    "Propuesta",
    "EOI",
    "Presupuesto",
    "Subasta Eletrónico",
    "RFP",
    "RFI",
    "Contratación directa",
    "Forecast",
    "Capacitación",
    "Otro",
)

DB_SITUACIONES = (
    "Abierto",
    "En analisis",
    "Adjudicado",
    "Perdido",
    "Desistido",
    "Postergado sine-die",
    "Cancelado",
    "En monitoramiento",
    "Presupuesto",
)

DB_MOTIVOS_RECHAZO = (
    "Bajo presupuesto",
    "Fuera de alcance",
    "No cumplimos requerimientos",
    "Falta de tiempo",
    "No conseguimos socios locales",
    "Desafíos administrativos",
    "Error de SIDOC",
    "Dos o más anteriores",
    "Otro",
)

DB_ESTADOS_SEGUIMIENTO = (
    "Descartada",
    "Pendiente",
    "EOI Presentada",
    "Propuesta Presentada",
)

PROCESS_TYPE_TO_DB = {
    "EOI": "EOI",
    "RFP": "RFP",
    "RFQ": "RFI",
    "Tender": "Propuesta",
    "Procurement Notice": "Propuesta",
    "Other": "Otro",
}


def normalize_catalog_value(value: Any, allowed_values: tuple[str, ...], *, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default

    by_key = {_catalog_key(item): item for item in allowed_values}
    return by_key.get(_catalog_key(text), default)


def normalize_process_type(value: Any, *, default: str = "Otro") -> str:
    if value is None:
        return default
    text = getattr(value, "value", value)
    mapped = PROCESS_TYPE_TO_DB.get(str(text).strip())
    if mapped:
        return mapped
    return normalize_catalog_value(text, DB_TIPOS_PROPUESTA, default=default) or default


def _catalog_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(ascii_text.casefold().split())
