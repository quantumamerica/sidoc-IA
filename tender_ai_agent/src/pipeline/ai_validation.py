from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from clients.base import BaseAIClient
from clients.judge import build_judge_client, judge_label
from config.settings import Settings
from models.schemas import (
    PipelineStage,
    RejectedOpportunity,
    RejectionReason,
    ValidatedOpportunity,
)
from utils.dates import today_utc_date
from utils.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)

PROMPT_PATH = "agents/ai_business_validation_agent.md"
# Valores del catalogo `filtro_gemini` que espera SGQ: se mantienen aunque el juez sea Claude.
FILTRO_SELECCIONADA = "Seleccionada por Gemini"
FILTRO_DESCARTADA = "Descartada por Gemini"
MAX_DESCRIPTION_CHARS = 6000
MAX_SUMMARY_CHARS = 2000
MAX_EVIDENCE_CHARS = 2000
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "relevance_score": {"type": "number"},
        "is_consulting": {"type": "boolean"},
        "is_works_or_equipment": {"type": "boolean"},
        "is_tender_notice": {"type": "boolean"},
        "decision": {"type": "string", "enum": ["SI", "NO"]},
        "reason": {"type": "string"},
    },
    "required": ["relevance_score", "is_consulting", "is_works_or_equipment", "is_tender_notice", "decision", "reason"],
}


@dataclass
class JudgeVerdict:
    approved: bool
    score: float | None
    reason_text: str
    rejection_reason: RejectionReason | None = None
    model: str | None = None


class AiBusinessValidationService:
    """Juez de negocio (LLM-as-judge) con Claude o Gemini. Salida binaria: aprueba o descarta."""

    def __init__(
        self,
        settings: Settings,
        client: BaseAIClient | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or build_judge_client(settings)
        self.prompt_loader = prompt_loader or PromptLoader(settings.prompts_dir)
        self.threshold = settings.ai_validation_threshold
        self.delay_seconds = settings.ai_validation_delay_seconds

    def validate(
        self, opportunities: list[ValidatedOpportunity]
    ) -> tuple[list[ValidatedOpportunity], list[RejectedOpportunity]]:
        if not opportunities:
            return [], []

        if not self.settings.ai_validation_enabled:
            logger.info("Validacion IA desactivada (AI_VALIDATION_ENABLED=false); se omite el juez IA.")
            return opportunities, []

        if not self.client.is_configured():
            logger.warning("Validacion IA omitida: el juez no tiene API key configurada. Las oportunidades pasan sin juzgar.")
            return opportunities, []

        approved: list[ValidatedOpportunity] = []
        rejected: list[RejectedOpportunity] = []

        for index, opportunity in enumerate(opportunities):
            verdict = self._judge(opportunity)
            self._apply_verdict(opportunity, verdict, approved, rejected)
            if self.delay_seconds > 0 and index < len(opportunities) - 1:
                time.sleep(self.delay_seconds)

        logger.info(
            "Juez IA %s completado entrada=%s validadas=%s descartadas=%s",
            judge_label(self.client),
            len(opportunities),
            len(approved),
            len(rejected),
        )
        return approved, rejected

    def _judge(self, opportunity: ValidatedOpportunity) -> JudgeVerdict:
        prompt = self.prompt_loader.render_file(PROMPT_PATH, self._build_context(opportunity))

        response = self.client.run_agent(prompt, response_format="json", stage="ai_validation", json_schema=JUDGE_SCHEMA)
        if response.error or response.parsed_json is None:
            logger.warning(
                "Juez IA sin veredicto utilizable titulo=%r error=%s; se descarta por precaucion.",
                self._title(opportunity)[:80],
                response.error,
            )
            return JudgeVerdict(
                approved=False,
                score=None,
                reason_text=f"Validacion IA no concluyente: {response.error or 'respuesta no parseable'}.",
                rejection_reason=RejectionReason.AI_VALIDATION_ERROR,
            )

        verdict = self._interpret(response.parsed_json)
        verdict.model = response.metadata.get("served_model") or response.model
        return verdict

    def _build_context(self, opportunity: ValidatedOpportunity) -> dict[str, str]:
        descripcion = (
            opportunity.description_raw
            or opportunity.descripcion
            or opportunity.description_summary
            or ""
        )
        resumen = opportunity.description_summary or opportunity.resumen_descrip or ""
        deadline = opportunity.deadline_normalized or opportunity.deadline
        publicacion = opportunity.publication_date_normalized or opportunity.fecha_publicacion
        return {
            "fecha_actual": today_utc_date().isoformat(),
            "fuente": opportunity.source_name or opportunity.fuente or "",
            "fecha_publicacion": publicacion.isoformat() if publicacion else "",
            "evidencia": (opportunity.evidence_text or "")[:MAX_EVIDENCE_CHARS],
            "titulo": self._title(opportunity),
            "resumen": resumen[:MAX_SUMMARY_CHARS],
            "descripcion": descripcion[:MAX_DESCRIPTION_CHARS],
            "organismo": opportunity.contracting_authority or opportunity.organismo_contratado or "",
            "pais": opportunity.country or opportunity.geographic_scope or "",
            "deadline": deadline.isoformat() if deadline else "",
            "url": opportunity.official_url or opportunity.url or "",
            "process_type": getattr(opportunity.process_type, "value", opportunity.process_type) or "",
        }

    @staticmethod
    def _title(opportunity: ValidatedOpportunity) -> str:
        return opportunity.normalized_title or opportunity.raw_title or opportunity.titulo_estudio or ""

    def _interpret(self, payload: object) -> JudgeVerdict:
        if not isinstance(payload, dict):
            return JudgeVerdict(False, None, "Respuesta IA con formato inesperado.", RejectionReason.AI_VALIDATION_ERROR)

        score = self._coerce_score(payload.get("relevance_score"))
        is_consulting = self._coerce_bool(payload.get("is_consulting"), default=True)
        is_works = self._coerce_bool(payload.get("is_works_or_equipment"), default=False)
        is_tender_notice = self._coerce_bool(payload.get("is_tender_notice"), default=True)
        decision = str(payload.get("decision") or "").strip().upper()
        reason_text = str(payload.get("reason") or "").strip() or "Sin justificacion provista por el juez IA."

        if not is_tender_notice:
            return JudgeVerdict(False, score, reason_text, RejectionReason.NOT_A_TENDER)
        if is_works:
            return JudgeVerdict(False, score, reason_text, RejectionReason.EPC_OR_WORKS)
        if not is_consulting:
            return JudgeVerdict(False, score, reason_text, RejectionReason.NOT_CONSULTING)
        if decision == "NO":
            return JudgeVerdict(False, score, reason_text, RejectionReason.LOW_BUSINESS_RELEVANCE)
        if score is None or score < self.threshold:
            return JudgeVerdict(False, score, reason_text, RejectionReason.LOW_BUSINESS_RELEVANCE)
        return JudgeVerdict(True, score, reason_text)

    def _apply_verdict(
        self,
        opportunity: ValidatedOpportunity,
        verdict: JudgeVerdict,
        approved: list[ValidatedOpportunity],
        rejected: list[RejectedOpportunity],
    ) -> None:
        opportunity.ai_confidence = verdict.score
        opportunity.metadata = {
            **opportunity.metadata,
            "ai_judge": {"model": verdict.model, "score": verdict.score, "reason": verdict.reason_text},
        }
        opportunity.audit_notes = [*opportunity.audit_notes, self._build_note(verdict)]

        if verdict.approved:
            opportunity.filtro_gemini = FILTRO_SELECCIONADA
            approved.append(opportunity)
            return

        opportunity.filtro_gemini = FILTRO_DESCARTADA
        rejected.append(
            RejectedOpportunity(
                **opportunity.model_dump(),
                title=opportunity.titulo_estudio,
                stage=PipelineStage.AI_VALIDATION,
                reason=verdict.rejection_reason or RejectionReason.LOW_BUSINESS_RELEVANCE,
            )
        )

    def _build_note(self, verdict: JudgeVerdict) -> str:
        score_text = f"{verdict.score:.2f}" if verdict.score is not None else "n/d"
        decision = "validada" if verdict.approved else "descartada"
        return f"[{judge_label(self.client)}] decision={decision} score={score_text}: {verdict.reason_text}"

    @staticmethod
    def _coerce_score(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        if isinstance(value, str):
            try:
                return max(0.0, min(1.0, float(value.strip())))
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_bool(value: object, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "si", "sí", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0"}:
                return False
        return default
