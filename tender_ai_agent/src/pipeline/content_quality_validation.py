from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from clients.gemini_client import GeminiClient
from config.settings import Settings
from models.schemas import (
    PipelineStage,
    RejectedOpportunity,
    RejectionReason,
    ValidatedOpportunity,
)
from utils.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)

PROMPT_PATH = "agents/content_quality_validation_agent.md"
MAX_DESCRIPTION_CHARS = 6000
MAX_SUMMARY_CHARS = 2000


@dataclass
class ContentQualityVerdict:
    approved: bool
    reason_text: str
    rejection_reason: RejectionReason | None = None


class ContentQualityValidationService:
    """Compuerta estricta: descarta oportunidades cuyo texto no permite entender el objeto."""

    def __init__(
        self,
        settings: Settings,
        client: GeminiClient | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or GeminiClient(settings)
        self.prompt_loader = prompt_loader or PromptLoader(settings.prompts_dir)
        self.delay_seconds = settings.ai_validation_delay_seconds

    def validate(
        self, opportunities: list[ValidatedOpportunity]
    ) -> tuple[list[ValidatedOpportunity], list[RejectedOpportunity]]:
        if not opportunities:
            return [], []

        if not self.settings.content_quality_validation_enabled:
            logger.info(
                "Validacion de calidad de contenido desactivada "
                "(CONTENT_QUALITY_VALIDATION_ENABLED=false); se omite la compuerta."
            )
            return opportunities, []

        if not self.client.is_configured():
            logger.error(
                "Validacion de calidad de contenido activa pero GOOGLE_API_KEY no esta configurada; "
                "se descartan las oportunidades por precaucion."
            )
            return self._reject_all(
                opportunities,
                "Validacion de calidad de contenido no ejecutada: GOOGLE_API_KEY no esta configurada.",
                RejectionReason.CONTENT_QUALITY_VALIDATION_ERROR,
            )

        approved: list[ValidatedOpportunity] = []
        rejected: list[RejectedOpportunity] = []

        for index, opportunity in enumerate(opportunities):
            verdict = self._judge(opportunity)
            self._apply_verdict(opportunity, verdict, approved, rejected)
            if self.delay_seconds > 0 and index < len(opportunities) - 1:
                time.sleep(self.delay_seconds)

        logger.info(
            "Validacion de calidad de contenido completada entrada=%s validadas=%s descartadas=%s",
            len(opportunities),
            len(approved),
            len(rejected),
        )
        return approved, rejected

    def _judge(self, opportunity: ValidatedOpportunity) -> ContentQualityVerdict:
        prompt = self.prompt_loader.render_file(PROMPT_PATH, self._build_context(opportunity))

        response = self.client.run_agent(prompt, response_format="json", stage="content_quality_validation")
        if response.error or response.parsed_json is None:
            logger.warning(
                "Validacion de calidad sin veredicto utilizable titulo=%r error=%s; se descarta.",
                self._title(opportunity)[:80],
                response.error,
            )
            return ContentQualityVerdict(
                approved=False,
                reason_text=f"Validacion de calidad no concluyente: {response.error or 'respuesta no parseable'}.",
                rejection_reason=RejectionReason.CONTENT_QUALITY_VALIDATION_ERROR,
            )

        return self._interpret(response.parsed_json)

    def _build_context(self, opportunity: ValidatedOpportunity) -> dict[str, str]:
        descripcion = (
            opportunity.description_raw
            or opportunity.descripcion
            or opportunity.description_summary
            or ""
        )
        resumen = opportunity.description_summary or opportunity.resumen_descrip or ""
        return {
            "titulo": self._title(opportunity),
            "resumen": resumen[:MAX_SUMMARY_CHARS],
            "descripcion": descripcion[:MAX_DESCRIPTION_CHARS],
        }

    @staticmethod
    def _title(opportunity: ValidatedOpportunity) -> str:
        return opportunity.normalized_title or opportunity.raw_title or opportunity.titulo_estudio or ""

    def _interpret(self, payload: object) -> ContentQualityVerdict:
        if not isinstance(payload, dict):
            return ContentQualityVerdict(
                False,
                "Respuesta de calidad con formato inesperado.",
                RejectionReason.CONTENT_QUALITY_VALIDATION_ERROR,
            )

        is_complete = self._coerce_bool(payload.get("is_complete"), default=False)
        has_clear_object = self._coerce_bool(payload.get("has_clear_object"), default=False)
        has_specific_scope = self._coerce_bool(payload.get("has_specific_scope"), default=False)
        is_too_generic = self._coerce_bool(payload.get("is_too_generic"), default=True)
        decision = str(payload.get("decision") or "").strip().upper()
        reason_text = str(payload.get("reason") or "").strip() or "Sin justificacion provista por la validacion de calidad."

        if not is_complete or not has_clear_object or not has_specific_scope or is_too_generic or decision != "SI":
            return ContentQualityVerdict(False, reason_text, RejectionReason.INCOMPLETE_CONTENT)

        return ContentQualityVerdict(True, reason_text)

    def _apply_verdict(
        self,
        opportunity: ValidatedOpportunity,
        verdict: ContentQualityVerdict,
        approved: list[ValidatedOpportunity],
        rejected: list[RejectedOpportunity],
    ) -> None:
        opportunity.audit_notes = [*opportunity.audit_notes, self._build_note(verdict)]

        if verdict.approved:
            approved.append(opportunity)
            return

        rejected.append(
            RejectedOpportunity(
                **opportunity.model_dump(),
                title=opportunity.titulo_estudio,
                stage=PipelineStage.CONTENT_QUALITY_VALIDATION,
                reason=verdict.rejection_reason or RejectionReason.INCOMPLETE_CONTENT,
            )
        )

    def _reject_all(
        self,
        opportunities: list[ValidatedOpportunity],
        reason_text: str,
        rejection_reason: RejectionReason,
    ) -> tuple[list[ValidatedOpportunity], list[RejectedOpportunity]]:
        rejected: list[RejectedOpportunity] = []
        for opportunity in opportunities:
            verdict = ContentQualityVerdict(False, reason_text, rejection_reason)
            self._apply_verdict(opportunity, verdict, [], rejected)
        return [], rejected

    @staticmethod
    def _build_note(verdict: ContentQualityVerdict) -> str:
        decision = "validada" if verdict.approved else "descartada"
        return f"[Gemini calidad contenido] decision={decision}: {verdict.reason_text}"

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
