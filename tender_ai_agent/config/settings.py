from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


SUPPORTED_PROVIDERS = {"openai", "perplexity"}
DEFAULT_PROVIDER_LIST = ["openai", "perplexity"]


class Settings(BaseModel):
    project_root: Path
    app_env: str = "development"
    log_level: str = "INFO"
    dry_run: bool = False

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"
    perplexity_api_key: str | None = None
    perplexity_model: str = "sonar-pro"

    database_url: str | None = None
    db_table_name: str = "licitacion"
    default_db_estado: str = "Sin Analizar"
    default_db_seleccion: str | None = "Seleccionada por Agente IA"
    default_negocio_id: int | None = None
    default_colaborador_id: int | None = None
    default_responsable_id: int | None = None
    default_filial_id: int | None = None
    default_filtro_gemini: str | None = "No analizada"
    default_comentarios_personales: str | None = None
    default_estado_seguimiento: str | None = "Pendiente"
    default_situacion: str | None = "Abierto"
    default_controlcomercial: bool = False
    default_comentario_prefix: str = "Cargado automaticamente por tender_ai_agent"

    default_providers: list[str] = Field(default_factory=lambda: ["openai", "perplexity"])
    default_regions: list[str] = Field(default_factory=lambda: ["all"])

    output_dir: Path
    log_dir: Path
    request_timeout_seconds: int = 60
    max_results_per_source: int = 20

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"

    @property
    def prompts_dir(self) -> Path:
        return self.project_root / "prompts"

    @property
    def db_opportunities_table(self) -> str:
        return self.db_table_name


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_providers(value: str | None) -> list[str]:
    raw_providers = [item.lower() for item in _parse_csv(value, DEFAULT_PROVIDER_LIST)]
    if raw_providers in (["all"], ["both"]):
        return DEFAULT_PROVIDER_LIST

    providers = list(dict.fromkeys(raw_providers))
    invalid = [provider for provider in providers if provider not in SUPPORTED_PROVIDERS]
    if invalid:
        valid_values = ", ".join(sorted(SUPPORTED_PROVIDERS | {"all", "both"}))
        raise ValueError(
            "DEFAULT_PROVIDERS contiene proveedor(es) no soportado(s): "
            f"{', '.join(invalid)}. Valores validos: {valid_values}; "
            "o una lista separada por comas, por ejemplo: openai,perplexity."
        )
    return providers


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    return int(value)


def load_settings(project_root: Path) -> Settings:
    load_dotenv(project_root / ".env")

    output_dir = project_root / os.getenv("OUTPUT_DIR", "outputs")
    log_dir = project_root / os.getenv("LOG_DIR", "logs")

    return Settings(
        project_root=project_root,
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dry_run=_parse_bool(os.getenv("DRY_RUN"), default=False),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY") or None,
        perplexity_model=os.getenv("PERPLEXITY_MODEL", "sonar-pro"),
        database_url=os.getenv("DATABASE_URL") or None,
        db_table_name=os.getenv("DB_TABLE_NAME") or os.getenv("DB_OPPORTUNITIES_TABLE", "licitacion"),
        default_db_estado=os.getenv("DEFAULT_DB_ESTADO", "Sin Analizar"),
        default_db_seleccion=os.getenv("DEFAULT_DB_SELECCION", "Seleccionada por Agente IA") or "Seleccionada por Agente IA",
        default_negocio_id=_parse_optional_int(os.getenv("DEFAULT_NEGOCIO_ID")),
        default_colaborador_id=_parse_optional_int(os.getenv("DEFAULT_COLABORADOR_ID")),
        default_responsable_id=_parse_optional_int(os.getenv("DEFAULT_RESPONSABLE_ID")),
        default_filial_id=_parse_optional_int(os.getenv("DEFAULT_FILIAL_ID")),
        default_filtro_gemini=os.getenv("DEFAULT_FILTRO_GEMINI", "No analizada") or None,
        default_comentarios_personales=os.getenv("DEFAULT_COMENTARIOS_PERSONALES") or None,
        default_estado_seguimiento=os.getenv("DEFAULT_ESTADO_SEGUIMIENTO", "Pendiente") or None,
        default_situacion=os.getenv("DEFAULT_SITUACION", "Abierto") or None,
        default_controlcomercial=_parse_bool(os.getenv("DEFAULT_CONTROLCOMERCIAL"), default=False),
        default_comentario_prefix=os.getenv("DEFAULT_COMENTARIO_PREFIX", "Cargado automaticamente por tender_ai_agent"),
        default_providers=_parse_providers(os.getenv("DEFAULT_PROVIDERS")),
        default_regions=_parse_csv(os.getenv("DEFAULT_REGIONS"), ["all"]),
        output_dir=output_dir,
        log_dir=log_dir,
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "60")),
        max_results_per_source=int(os.getenv("MAX_RESULTS_PER_SOURCE", "20")),
    )
