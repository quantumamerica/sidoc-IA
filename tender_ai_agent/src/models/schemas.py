from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from utils.dates import is_future_date, normalize_date


DB_COLUMNS = (
    "id",
    "id_fuente",
    "url",
    "fuente",
    "organismo_contratado",
    "titulo_estudio",
    "deadline",
    "ambito_geografico",
    "categoria",
    "fecha_publicacion",
    "fecha_modificacion",
    "descripcion",
    "idioma",
    "tema",
    "seleccion",
    "estado",
    "negocio_id",
    "referencia",
    "controlcomercial",
    "cant_palabras_match",
    "palabras_match",
    "resumen_descrip",
    "colaborador_id",
    "fecha_carga",
    "motivo_rechazo",
    "responsable_id",
    "situacion",
    "tipo_propuesta",
    "filial_id",
    "filtro_gemini",
    "seguimiento",
    "comentario",
    "comentarios_personales",
    "estado_seguimiento",
)


class ProviderName(str, Enum):
    OPENAI = "openai"
    PERPLEXITY = "perplexity"


class PipelineStage(str, Enum):
    DISCOVERY = "discovery"
    IDENTIFICATION = "identification"
    ELIGIBILITY = "eligibility"
    ENRICHMENT = "enrichment"
    VALIDATION = "validation"
    DEDUPLICATION = "deduplication"
    DB_MAPPING = "db_mapping"
    PERSISTENCE = "persistence"
    COMPARISON = "comparison"


class EligibilityStatus(str, Enum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class ValidationStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    NEEDS_REVIEW = "needs_review"


class RejectionReason(str, Enum):
    NO_DEADLINE = "no_deadline"
    DEADLINE_EXPIRED = "deadline_expired"
    MISSING_NORMALIZED_TITLE = "missing_normalized_title"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_REQUIRED = "captcha_required"
    NOT_CONSULTING = "not_consulting"
    INDIVIDUAL_CONSULTANT = "individual_consultant"
    EPC_OR_WORKS = "epc_or_works"
    EQUIPMENT_SUPPLY = "equipment_supply"
    CONSTRUCTION_SUPERVISION = "construction_supervision"
    ENVIRONMENTAL_ONLY = "environmental_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DUPLICATE = "duplicate"
    INVALID_URL = "invalid_url"
    OTHER = "other"


class ProcessType(str, Enum):
    EOI = "EOI"
    RFP = "RFP"
    RFQ = "RFQ"
    TENDER = "Tender"
    PROCUREMENT_NOTICE = "Procurement Notice"
    OTHER = "Other"


class SourcePriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceType(str, Enum):
    NATIONAL_PORTAL = "national_portal"
    REGULATOR = "regulator"
    UTILITY = "utility"
    MULTILATERAL = "multilateral"
    MUNICIPAL = "municipal"
    AGGREGATOR = "aggregator"
    OTHER = "other"


class SearchStrategy(str, Enum):
    DIRECT_PORTAL = "direct_portal"
    WEB_DISCOVERY = "web_discovery"
    CITY_SEARCH = "city_search"
    MULTILATERAL_SEARCH = "multilateral_search"
    SKIP_IF_LOGIN = "skip_if_login"


BooleanOrUnknown = bool | Literal["unknown"]


class SerializableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)

    def to_json_dict(self, *, exclude_none: bool = False) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=exclude_none)


class Source(SerializableModel):
    id: str
    name: str
    region: str
    country: str | None = None
    url: str | None = None
    requires_login: BooleanOrUnknown = "unknown"
    has_captcha: BooleanOrUnknown = "unknown"
    priority: SourcePriority = SourcePriority.MEDIUM
    enabled: bool = True
    source_type: SourceType = SourceType.OTHER
    search_strategy: SearchStrategy = SearchStrategy.WEB_DISCOVERY
    notes: str | None = None
    keywords: list[str] = Field(default_factory=list)
    search_domains: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    fallback_queries: list[str] = Field(default_factory=list)
    language_hint: str | None = None
    day_group_original: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def sync_language_alias(self) -> Source:
        if self.language_hint is None and self.language is not None:
            self.language_hint = self.language
        if self.language is None and self.language_hint is not None:
            self.language = self.language_hint
        return self

    @property
    def is_restricted(self) -> bool:
        return self.requires_login is True or self.has_captcha is True


class RegionConfig(SerializableModel):
    key: str
    description: str
    prompt_file: str

    @property
    def label(self) -> str:
        return self.description

    @property
    def discovery_prompt(self) -> str:
        return self.prompt_file.split("prompts/discovery/", 1)[-1]


class OpenWebSourcePolicy(SerializableModel):
    description: str | None = None
    allowed_source_types: list[str] = Field(default_factory=list)
    excluded_source_types: list[str] = Field(default_factory=list)


class OpenWebTheme(SerializableModel):
    id: str
    name: str
    search_queries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class OpenWebRegionConfig(SerializableModel):
    languages: list[str] = Field(default_factory=list)
    region_scope: str | None = None
    query_terms: list[str] = Field(default_factory=list)


class OpenWebDiscoveryConfig(SerializableModel):
    enabled: bool = True
    official_source_policy: OpenWebSourcePolicy = Field(default_factory=OpenWebSourcePolicy)
    themes: list[OpenWebTheme] = Field(default_factory=list)
    regions: dict[str, OpenWebRegionConfig] = Field(default_factory=dict)


class RawProviderResult(SerializableModel):
    provider: ProviderName
    region: str
    source_id: str
    source_name: str | None = None
    source_url: str | None = None
    execution_date: date | None = None
    run_id: str | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    discovered_by_prompt: str | None = None
    prompt_name: str
    content: str
    raw_response_path: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    cost_estimate_usd: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def captured_at(self) -> datetime:
        return self.discovered_at


class OpportunityDbFields(SerializableModel):
    id: int | None = None
    id_fuente: str | None = None
    url: str | None = None
    fuente: str | None = None
    organismo_contratado: str | None = None
    titulo_estudio: str | None = None
    deadline: date | None = None
    ambito_geografico: str | None = None
    categoria: str | None = None
    fecha_publicacion: date | None = None
    fecha_modificacion: date | None = None
    descripcion: str | None = None
    idioma: str | None = None
    tema: str | None = None
    seleccion: str | None = None
    estado: str | None = None
    negocio_id: int | None = None
    referencia: str | None = None
    controlcomercial: bool | None = None
    cant_palabras_match: int | None = None
    palabras_match: str | None = None
    resumen_descrip: str | None = None
    colaborador_id: int | None = None
    fecha_carga: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
    motivo_rechazo: str | None = None
    responsable_id: int | None = None
    situacion: str | None = None
    tipo_propuesta: str | None = None
    filial_id: int | None = None
    filtro_gemini: str | None = None
    seguimiento: str | None = None
    comentario: str | None = None
    comentarios_personales: str | None = None
    estado_seguimiento: str | None = None

    @field_validator("deadline", "fecha_publicacion", "fecha_modificacion", mode="before")
    @classmethod
    def _normalize_db_dates(cls, value: Any) -> date | None:
        return normalize_date(value)

    @field_validator("palabras_match", mode="before")
    @classmethod
    def _normalize_keyword_string(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)


class OpportunityInternalFields(SerializableModel):
    provider: ProviderName | None = None
    region: str | None = None
    source_id: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    execution_date: date | None = None
    run_id: str | None = None
    discovered_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
    discovered_by_prompt: str | None = None
    raw_title: str | None = None
    normalized_title: str | None = None
    official_url: str | None = None
    all_urls: list[str] = Field(default_factory=list)
    contracting_authority: str | None = None
    country: str | None = None
    geographic_scope: str | None = None
    process_type: ProcessType | None = None
    consultant_type: str | None = None
    deadline_raw: str | None = None
    deadline_normalized: date | None = None
    publication_date_raw: str | None = None
    publication_date_normalized: date | None = None
    modification_date_raw: str | None = None
    modification_date_normalized: date | None = None
    description_raw: str | None = None
    description_summary: str | None = None
    language: str | None = None
    topic: str | None = None
    category: str | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    matched_keywords_count: int | None = None
    eligibility_status: EligibilityStatus = EligibilityStatus.PENDING
    validation_status: ValidationStatus = ValidationStatus.PENDING
    rejection_reason: RejectionReason | str | None = None
    evidence_text: str | None = None
    evidence_urls: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    duplicate_group_id: str | None = None
    duplicate_of_url: str | None = None
    source_confidence: float | None = None
    ai_confidence: float | None = None
    provider_confidence: float | None = None
    openai_payload: dict[str, Any] | None = None
    perplexity_payload: dict[str, Any] | None = None
    raw_response_path: str | None = None
    audit_notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "execution_date",
        "deadline_normalized",
        "publication_date_normalized",
        "modification_date_normalized",
        mode="before",
    )
    @classmethod
    def _normalize_internal_dates(cls, value: Any) -> date | None:
        return normalize_date(value)


class CandidateOpportunity(OpportunityDbFields, OpportunityInternalFields):
    model_config = ConfigDict(extra="ignore", validate_assignment=False)

    provider: ProviderName

    @model_validator(mode="before")
    @classmethod
    def normalize_ai_field_aliases(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        aliases = {
            "reference": "referencia",
            "title": "raw_title",
            "description": "description_raw",
            "summary": "description_summary",
            "authority": "contracting_authority",
            "organism": "contracting_authority",
            "organismo": "contracting_authority",
            "country_name": "country",
            "official_link": "official_url",
        }
        normalized = dict(values)
        for source_key, target_key in aliases.items():
            if source_key in normalized and target_key not in normalized:
                normalized[target_key] = normalized[source_key]

        if "available_documents" in normalized:
            metadata = dict(normalized.get("metadata") or {})
            metadata["available_documents"] = normalized["available_documents"]
            normalized["metadata"] = metadata
        return normalized

    @model_validator(mode="after")
    def sync_common_fields(self) -> CandidateOpportunity:
        if self.official_url and self.url is None:
            self.url = self.official_url
        if self.url and self.official_url is None:
            self.official_url = self.url
        if self.source_id and self.id_fuente is None:
            self.id_fuente = self.source_id
        if self.source_name and self.fuente is None:
            self.fuente = self.source_name
        if self.contracting_authority and self.organismo_contratado is None:
            self.organismo_contratado = self.contracting_authority
        if self.raw_title and self.titulo_estudio is None:
            self.titulo_estudio = self.raw_title
        if self.normalized_title and self.titulo_estudio is None:
            self.titulo_estudio = self.normalized_title
        if self.geographic_scope and self.ambito_geografico is None:
            self.ambito_geografico = self.geographic_scope
        if self.category and self.categoria is None:
            self.categoria = self.category
        if self.language and self.idioma is None:
            self.idioma = self.language
        if self.topic and self.tema is None:
            self.tema = self.topic
        if self.description_raw and self.descripcion is None:
            self.descripcion = self.description_raw
        if self.description_summary and self.resumen_descrip is None:
            self.resumen_descrip = self.description_summary
        if self.deadline_raw and self.deadline_normalized is None and self.deadline is None:
            normalized_deadline = normalize_date(self.deadline_raw)
            if normalized_deadline:
                self.deadline_normalized = normalized_deadline
                self.deadline = normalized_deadline
        if self.publication_date_raw and self.publication_date_normalized is None and self.fecha_publicacion is None:
            normalized_publication_date = normalize_date(self.publication_date_raw)
            if normalized_publication_date:
                self.publication_date_normalized = normalized_publication_date
                self.fecha_publicacion = normalized_publication_date
        if self.modification_date_raw and self.modification_date_normalized is None and self.fecha_modificacion is None:
            normalized_modification_date = normalize_date(self.modification_date_raw)
            if normalized_modification_date:
                self.modification_date_normalized = normalized_modification_date
                self.fecha_modificacion = normalized_modification_date
        if self.deadline_normalized and self.deadline is None:
            self.deadline = self.deadline_normalized
        if self.deadline and self.deadline_normalized is None:
            self.deadline_normalized = self.deadline
        if self.publication_date_normalized and self.fecha_publicacion is None:
            self.fecha_publicacion = self.publication_date_normalized
        if self.modification_date_normalized and self.fecha_modificacion is None:
            self.fecha_modificacion = self.modification_date_normalized
        if self.matched_keywords and self.cant_palabras_match is None:
            self.cant_palabras_match = len(self.matched_keywords)
        if self.palabras_match is None and self.matched_keywords:
            self.palabras_match = ", ".join(self.matched_keywords)
        return self

    def deadline_is_future(self, reference_date: date | None = None) -> bool:
        return is_future_date(self.deadline_normalized or self.deadline, reference_date=reference_date)

    def to_db_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=exclude_none)
        return {
            column: payload.get(column)
            for column in DB_COLUMNS
            if not exclude_none or payload.get(column) is not None
        }

    def internal_metadata(self, *, exclude_none: bool = True) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=exclude_none)
        return {key: value for key, value in payload.items() if key not in DB_COLUMNS}


class EligibilityResult(SerializableModel):
    candidate: CandidateOpportunity
    is_eligible: bool
    reason: RejectionReason | str | None = None


class RejectedOpportunity(CandidateOpportunity):
    model_config = ConfigDict(extra="ignore", validate_assignment=False)

    provider: ProviderName | None = None
    title: str | None = None
    stage: PipelineStage
    reason: RejectionReason | str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def sync_rejection_fields(self) -> RejectedOpportunity:
        self.eligibility_status = EligibilityStatus.REJECTED
        if self.rejection_reason is None:
            self.rejection_reason = self.reason
        if self.motivo_rechazo is None:
            self.motivo_rechazo = self.reason.value if isinstance(self.reason, RejectionReason) else str(self.reason)
        if self.title and self.titulo_estudio is None:
            self.titulo_estudio = self.title
        return self


class EnrichedOpportunity(CandidateOpportunity):
    enrichment_notes: str | None = None


class ValidatedOpportunity(EnrichedOpportunity):
    validation_status: ValidationStatus = ValidationStatus.VALID
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def sync_validation(self) -> ValidatedOpportunity:
        if not self.deadline_is_future():
            self.validation_status = ValidationStatus.INVALID
        return self


class ValidationResult(SerializableModel):
    opportunity: EnrichedOpportunity
    is_valid: bool
    reason: RejectionReason | str | None = None


class DeduplicationResult(SerializableModel):
    unique_opportunities: list[ValidatedOpportunity] = Field(default_factory=list)
    duplicate_opportunities: list[CandidateOpportunity] = Field(default_factory=list)
    duplicate_groups: dict[str, list[str]] = Field(default_factory=dict)
    rejected_duplicates: list[RejectedOpportunity] = Field(default_factory=list)


class DbMappedOpportunity(OpportunityDbFields, OpportunityInternalFields):
    mapped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_validated(cls, opportunity: ValidatedOpportunity) -> DbMappedOpportunity:
        payload = opportunity.model_dump()
        allowed_fields = set(cls.model_fields)
        return cls(**{key: value for key, value in payload.items() if key in allowed_fields})

    def to_db_dict(self, *, exclude_none: bool = True) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=exclude_none)
        return {
            column: payload.get(column)
            for column in DB_COLUMNS
            if not exclude_none or payload.get(column) is not None
        }

    def internal_metadata(self, *, exclude_none: bool = True) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=exclude_none)
        return {key: value for key, value in payload.items() if key not in DB_COLUMNS}


class PipelineStageLog(SerializableModel):
    run_id: str
    stage: PipelineStage
    provider: ProviderName | None = None
    region: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    input_count: int = 0
    output_count: int = 0
    rejected_count: int = 0
    error_count: int = 0
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostReport(SerializableModel):
    provider: ProviderName | None = None
    run_id: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_usd: float | None = None
    currency: str = "USD"
    metadata: dict[str, Any] = Field(default_factory=dict)


class InsertResult(SerializableModel):
    inserted: bool
    skipped: bool = False
    duplicate: bool = False
    inserted_id: int | None = None
    reason: str | None = None
    url: str | None = None
    reference: str | None = None
    table_name: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderRunReport(SerializableModel):
    provider: ProviderName
    region: str
    sources_consulted: int = 0
    sources_skipped: int = 0
    raw_responses: int = 0
    candidates: int = 0
    eligible: int = 0
    enriched: int = 0
    valid: int = 0
    mapped: int = 0
    inserted: int = 0
    rejected: int = 0
    duplicated: int = 0
    errors: list[str] = Field(default_factory=list)
    cost_estimate_usd: float | None = None


class ProviderComparisonResult(SerializableModel):
    run_id: str
    compared_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    found_by_both: list[dict[str, Any]] = Field(default_factory=list)
    openai_only: list[dict[str, Any]] = Field(default_factory=list)
    perplexity_only: list[dict[str, Any]] = Field(default_factory=list)
    only_openai: list[str] = Field(default_factory=list)
    only_perplexity: list[str] = Field(default_factory=list)
    common: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    merged_opportunities: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PipelineRun(SerializableModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    dry_run: bool
    skip_db: bool = False
    region: str
    providers: list[ProviderName]
    provider_reports: list[ProviderRunReport] = Field(default_factory=list)
    approved_total: int = 0
    inserted_total: int = 0
    rejected_total: int = 0
    discarded_opportunities_summary: list[dict[str, Any]] = Field(default_factory=list)
    discovery_mode_summary: dict[str, dict[str, Any]] = Field(default_factory=dict)
    duplicated_total: int = 0
    omitted_sources_total: int = 0
    report_path: str | None = None
    comparison: dict[str, Any] = Field(default_factory=dict)
    stage_logs: list[PipelineStageLog] = Field(default_factory=list)
    cost_report: CostReport | None = None
    errors: list[str] = Field(default_factory=list)


class ProviderPipelineResult(SerializableModel):
    run_id: str
    provider: ProviderName
    region: str
    sources_consulted: list[Source] = Field(default_factory=list)
    sources_omitted: list[Source] = Field(default_factory=list)
    raw_results: list[RawProviderResult] = Field(default_factory=list)
    candidates: list[CandidateOpportunity] = Field(default_factory=list)
    eligible: list[CandidateOpportunity] = Field(default_factory=list)
    enriched: list[EnrichedOpportunity] = Field(default_factory=list)
    validated: list[ValidatedOpportunity] = Field(default_factory=list)
    duplicates: list[RejectedOpportunity] = Field(default_factory=list)
    mapped: list[DbMappedOpportunity] = Field(default_factory=list)
    discarded: list[RejectedOpportunity] = Field(default_factory=list)
    stage_logs: list[PipelineStageLog] = Field(default_factory=list)
    report: ProviderRunReport
    errors: list[str] = Field(default_factory=list)


# Backward-compatible names used by the initial pipeline skeleton.
SourceConfig = Source
RawProviderResponse = RawProviderResult
OpportunityCandidate = CandidateOpportunity
MappedOpportunity = DbMappedOpportunity
PipelineReport = PipelineRun
