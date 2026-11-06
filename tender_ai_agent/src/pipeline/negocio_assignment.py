from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from clients.anthropic_client import AnthropicClient
from clients.base import BaseAIClient
from config.db_catalogs import _catalog_key
from config.settings import Settings
from models.schemas import NegocioDefinition, ValidatedOpportunity
from pipeline.negocio_catalog import NegocioCatalog
from utils.aprendizaje import ORDEN_NEGOCIOS, cargar_aprendizaje
from utils.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)

PROMPT_PATH = "agents/negocio_assignment_agent.md"
MAX_DESCRIPTION_CHARS = 6000
MAX_SUMMARY_CHARS = 2000

WEIGHT_DOMINANT = 4.0
WEIGHT_STRONG = 3.0
WEIGHT_WEAK = 1.0
WEIGHT_EXCLUDING = -2.0

# Constante de saturacion para llevar el score crudo al rango 0-1: score = raw / (raw + K).
SCORE_SATURATION = 4.0

METHOD_RULES = "rules"
METHOD_CLAUDE = "claude"
METHOD_FALLBACK = "fallback"


@dataclass
class NegocioScore:
    slug: str
    nombre: str
    prioridad: int
    raw_score: float
    score: float
    dominant_hits: list[str] = field(default_factory=list)
    strong_hits: list[str] = field(default_factory=list)
    weak_hits: list[str] = field(default_factory=list)
    excluding_hits: list[str] = field(default_factory=list)


@dataclass
class RuleOutcome:
    slug: str
    detail: str


@dataclass
class NegocioDecision:
    slug: str | None
    nombre: str | None
    negocio_id: int | None
    confidence: float | None
    method: str
    detail: str
    reason: str
    scores: dict[str, float] = field(default_factory=dict)


class NegocioRuleScorer:
    """Scoring por palabras clave. Ya no decide el negocio: solo respalda al Juez 3 si Claude falla."""

    def __init__(self, definitions: list[NegocioDefinition]) -> None:
        self.definitions = definitions
        self._patterns: dict[str, dict[str, list[tuple[str, re.Pattern[str]]]]] = {
            definition.slug: {
                "dominantes": self._compile(definition.keywords_dominantes),
                "fuertes": self._compile(definition.keywords_fuertes),
                "debiles": self._compile(definition.keywords_debiles),
                "excluyentes": self._compile(definition.keywords_excluyentes),
            }
            for definition in definitions
        }

    def score_all(self, text: str) -> list[NegocioScore]:
        normalized = _catalog_key(text)
        scores = [self._score_one(definition, normalized) for definition in self.definitions]
        return sorted(scores, key=lambda item: (-item.score, item.prioridad))

    def decide(self, scores: list[NegocioScore], *, strong_threshold: float, margin: float) -> RuleOutcome | None:
        """Decision por reglas (solo para el fallback y la calibracion por CLI)."""
        if not scores:
            return None

        dominant = [item for item in scores if item.dominant_hits]
        if dominant:
            best = min(dominant, key=lambda item: item.prioridad)
            return RuleOutcome(best.slug, "dominante")

        top = scores[0]
        if top.score < strong_threshold:
            return None

        tied = [
            item
            for item in scores
            if item.score >= strong_threshold and (top.score - item.score) <= margin
        ]
        if len(tied) <= 1:
            return RuleOutcome(top.slug, "score")

        best = min(tied, key=lambda item: item.prioridad)
        return RuleOutcome(best.slug, "prioridad")

    def _score_one(self, definition: NegocioDefinition, normalized_text: str) -> NegocioScore:
        patterns = self._patterns[definition.slug]
        dominant_hits = self._hits(patterns["dominantes"], normalized_text)
        strong_hits = self._hits(patterns["fuertes"], normalized_text)
        weak_hits = self._hits(patterns["debiles"], normalized_text)
        excluding_hits = self._hits(patterns["excluyentes"], normalized_text)

        raw_score = (
            WEIGHT_DOMINANT * len(dominant_hits)
            + WEIGHT_STRONG * len(strong_hits)
            + WEIGHT_WEAK * len(weak_hits)
            + WEIGHT_EXCLUDING * len(excluding_hits)
        )
        raw_score = max(0.0, raw_score)

        return NegocioScore(
            slug=definition.slug,
            nombre=definition.nombre,
            prioridad=definition.prioridad,
            raw_score=round(raw_score, 3),
            score=round(raw_score / (raw_score + SCORE_SATURATION), 4) if raw_score > 0 else 0.0,
            dominant_hits=dominant_hits,
            strong_hits=strong_hits,
            weak_hits=weak_hits,
            excluding_hits=excluding_hits,
        )

    @staticmethod
    def _compile(keywords: list[str]) -> list[tuple[str, re.Pattern[str]]]:
        compiled: list[tuple[str, re.Pattern[str]]] = []
        for keyword in keywords:
            normalized = _catalog_key(keyword)
            if not normalized:
                continue
            compiled.append((keyword, re.compile(rf"\b{re.escape(normalized)}\b")))
        return compiled

    @staticmethod
    def _hits(patterns: list[tuple[str, re.Pattern[str]]], normalized_text: str) -> list[str]:
        return [keyword for keyword, pattern in patterns if pattern.search(normalized_text)]


def negocio_schema(slugs: list[str]) -> dict:
    """Esquema JSON del Juez 3: el slug solo puede ser uno del catalogo."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "negocio_slug": {"type": "string", "enum": slugs},
            "confidence": {"type": "number"},
            "alternativa_slug": {"anyOf": [{"type": "string", "enum": slugs}, {"type": "null"}]},
            "reason": {"type": "string"},
        },
        "required": ["negocio_slug", "confidence", "alternativa_slug", "reason"],
    }


class NegocioAssignmentService:
    """Juez 3: Claude asigna la unidad de negocio de QUANTUM a cada oportunidad que va a la base.

    Ya no decide por palabras clave. Las reglas de `negocios.yaml` solo se usan si Claude no
    responde (sin ANTHROPIC_API_KEY o con error), y en ese caso la oportunidad queda marcada
    para revision humana.
    """

    def __init__(
        self,
        settings: Settings,
        client: BaseAIClient | None = None,
        prompt_loader: PromptLoader | None = None,
        catalog: NegocioCatalog | None = None,
    ) -> None:
        self.settings = settings
        if client is None:
            client = AnthropicClient(settings)
            client.model = settings.negocio_judge_model
        self.client = client
        self.prompt_loader = prompt_loader or PromptLoader(settings.prompts_dir)
        self.catalog = catalog or NegocioCatalog(settings)
        self.ejemplos_asignacion = cargar_aprendizaje(settings.config_dir, ORDEN_NEGOCIOS).ejemplos_asignacion()
        self.strong_threshold = settings.negocio_rules_strong_threshold
        self.margin = settings.negocio_rules_margin
        self.delay_seconds = settings.negocio_assignment_delay_seconds
        self._scorer: NegocioRuleScorer | None = None

    @property
    def scorer(self) -> NegocioRuleScorer:
        if self._scorer is None:
            self._scorer = NegocioRuleScorer(self.catalog.definitions)
        return self._scorer

    def assign(self, opportunities: list[ValidatedOpportunity]) -> list[ValidatedOpportunity]:
        if not opportunities:
            return opportunities

        if not self.settings.negocio_assignment_enabled:
            logger.info(
                "Asignacion de negocio desactivada (NEGOCIO_ASSIGNMENT_ENABLED=false); "
                "se mantiene el negocio_id por defecto."
            )
            return opportunities

        judge_available = self.client.is_configured()
        if not judge_available:
            logger.warning(
                "Juez 3 (negocio) sin ANTHROPIC_API_KEY: se asigna por palabras clave y "
                "las oportunidades quedan marcadas para revision humana."
            )

        methods: dict[str, int] = {}
        sin_id: list[str] = []
        for index, opportunity in enumerate(opportunities):
            decision = self._decide(opportunity, judge_available=judge_available)
            self._apply_decision(opportunity, decision)
            methods[decision.method] = methods.get(decision.method, 0) + 1
            if decision.negocio_id is None:
                sin_id.append(decision.slug or "sin_asignar")
            if judge_available and self.delay_seconds > 0 and index < len(opportunities) - 1:
                time.sleep(self.delay_seconds)

        logger.info(
            "Asignacion de negocio completada entrada=%s por_claude=%s fallback=%s",
            len(opportunities),
            methods.get(METHOD_CLAUDE, 0),
            methods.get(METHOD_FALLBACK, 0),
        )
        if sin_id:
            logger.warning(
                "Oportunidades sin negocio_id resuelto: %s de %s (negocios: %s). "
                "Completar sidoc_id en negocios.yaml o verificar la tabla %s.",
                len(sin_id),
                len(opportunities),
                ", ".join(sorted(set(sin_id))),
                self.settings.negocio_table_name,
            )
        return opportunities

    def classify_text(self, text: str, *, use_judge: bool = False) -> tuple[list[NegocioScore], NegocioDecision]:
        """Clasifica un texto suelto. Usado por el CLI: con use_judge consulta a Claude."""
        scores = self.scorer.score_all(text)
        if use_judge and self.client.is_configured():
            context = {key: "" for key in self._build_context_keys()}
            context["titulo"] = text
            decision = self._ask_judge(context, title=text)
            if decision is not None:
                return scores, decision
        return scores, self._fallback_decision(text, "consulta sin Juez 3")

    def _decide(self, opportunity: ValidatedOpportunity, *, judge_available: bool) -> NegocioDecision:
        context = self._build_context(opportunity)
        if judge_available:
            decision = self._ask_judge(context, title=context["titulo"])
            if decision is not None:
                return decision
            return self._fallback_decision(self._scoring_text(context), "Juez 3 sin veredicto utilizable")
        return self._fallback_decision(self._scoring_text(context), "Juez 3 sin ANTHROPIC_API_KEY")

    def _ask_judge(self, context: dict[str, str], *, title: str) -> NegocioDecision | None:
        variables = {
            **context,
            "negocios_catalogo": self.catalog.catalog_summary(),
            "ejemplos_asignacion": self.ejemplos_asignacion,
        }
        prompt = self.prompt_loader.render_file(PROMPT_PATH, variables)
        slugs = [definition.slug for definition in self.catalog.definitions]
        response = self.client.run_agent(
            prompt, response_format="json", stage="negocio_assignment", json_schema=negocio_schema(slugs)
        )

        if response.error or response.parsed_json is None:
            logger.warning(
                "Juez 3 sin veredicto utilizable titulo=%r error=%s; se usa fallback.",
                title[:80],
                response.error,
            )
            return None

        payload = response.parsed_json
        if not isinstance(payload, dict):
            logger.warning("Juez 3 con formato inesperado titulo=%r; se usa fallback.", title[:80])
            return None

        slug = str(payload.get("negocio_slug") or "").strip()
        definition = self.catalog.by_slug(slug)
        if definition is None:
            logger.warning("Juez 3 con slug desconocido slug=%r titulo=%r; se usa fallback.", slug, title[:80])
            return None

        reason = str(payload.get("reason") or "").strip() or "Sin justificacion provista por el Juez 3."
        alternativa = str(payload.get("alternativa_slug") or "").strip()
        if alternativa and alternativa != slug and self.catalog.by_slug(alternativa) is not None:
            reason = f"{reason} Alternativa considerada: {alternativa}."

        model = (response.metadata or {}).get("served_model") or response.model
        return NegocioDecision(
            slug=definition.slug,
            nombre=definition.nombre,
            negocio_id=self.catalog.negocio_id(definition.slug),
            confidence=self._coerce_score(payload.get("confidence")),
            method=METHOD_CLAUDE,
            detail=model or "claude",
            reason=reason,
        )

    def _fallback_decision(self, text: str, motivo: str) -> NegocioDecision:
        """Solo si Claude no responde: mayor score de palabras clave, o DEFAULT_NEGOCIO_ID."""
        scores = self.scorer.score_all(text)
        outcome = self.scorer.decide(scores, strong_threshold=self.strong_threshold, margin=self.margin)
        best = next((item for item in scores if item.slug == outcome.slug), None) if outcome else None
        if best is None and scores and scores[0].raw_score > 0:
            best = scores[0]
        if best is not None:
            return NegocioDecision(
                slug=best.slug,
                nombre=best.nombre,
                negocio_id=self.catalog.negocio_id(best.slug),
                confidence=best.score,
                method=METHOD_FALLBACK,
                detail="palabras_clave",
                reason=f"Fallback por {motivo}: se toma el negocio de mayor score de palabras clave. Revisar.",
                scores=self._scores_map(scores),
            )

        return NegocioDecision(
            slug=None,
            nombre=None,
            negocio_id=self.settings.default_negocio_id,
            confidence=None,
            method=METHOD_FALLBACK,
            detail="default",
            reason=f"Fallback por {motivo}: sin senales de palabras clave, se usa DEFAULT_NEGOCIO_ID. Revisar.",
            scores=self._scores_map(scores),
        )

    def _apply_decision(self, opportunity: ValidatedOpportunity, decision: NegocioDecision) -> None:
        opportunity.negocio_id = decision.negocio_id
        opportunity.negocio_slug = decision.slug
        opportunity.negocio_nombre = decision.nombre
        opportunity.negocio_confidence = decision.confidence
        opportunity.negocio_assignment_method = decision.method
        opportunity.negocio_scores = decision.scores
        needs_review = decision.method == METHOD_FALLBACK or (
            decision.confidence is None or decision.confidence < self.settings.negocio_review_threshold
        )
        if needs_review:
            opportunity.requires_human_review = True
        opportunity.metadata = {
            **(opportunity.metadata or {}),
            "negocio_judge": {
                "method": decision.method,
                "model": decision.detail if decision.method == METHOD_CLAUDE else None,
                "slug": decision.slug,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "needs_review": needs_review,
            },
        }
        opportunity.audit_notes = [*opportunity.audit_notes, self._build_note(decision)]

    @staticmethod
    def _build_context_keys() -> tuple[str, ...]:
        return ("titulo", "organismo", "pais", "fuente", "tema", "categoria", "resumen", "descripcion", "motivo_juez")

    def _build_context(self, opportunity: ValidatedOpportunity) -> dict[str, str]:
        descripcion = (
            opportunity.description_raw
            or opportunity.descripcion
            or opportunity.description_summary
            or ""
        )
        resumen = opportunity.description_summary or opportunity.resumen_descrip or ""
        judge = (opportunity.metadata or {}).get("ai_judge") or {}
        return {
            "titulo": self._title(opportunity),
            "organismo": opportunity.contracting_authority or opportunity.organismo_contratado or "",
            "pais": opportunity.country or opportunity.geographic_scope or "",
            "fuente": opportunity.source_name or opportunity.fuente or "",
            "tema": opportunity.topic or opportunity.tema or "",
            "categoria": opportunity.category or opportunity.categoria or "",
            "resumen": resumen[:MAX_SUMMARY_CHARS],
            "descripcion": descripcion[:MAX_DESCRIPTION_CHARS],
            "motivo_juez": str(judge.get("reason") or "")[:MAX_SUMMARY_CHARS],
        }

    @staticmethod
    def _scoring_text(context: dict[str, str]) -> str:
        return " ".join(
            part
            for part in (
                context["titulo"],
                context["tema"],
                context["categoria"],
                context["resumen"],
                context["descripcion"],
            )
            if part
        )

    @staticmethod
    def _scores_map(scores: list[NegocioScore]) -> dict[str, float]:
        return {item.slug: item.score for item in scores}

    @staticmethod
    def _title(opportunity: ValidatedOpportunity) -> str:
        return opportunity.normalized_title or opportunity.raw_title or opportunity.titulo_estudio or ""

    @staticmethod
    def _build_note(decision: NegocioDecision) -> str:
        confianza = f"{decision.confidence:.2f}" if decision.confidence is not None else "n/d"
        quien = "Juez 3 Claude" if decision.method == METHOD_CLAUDE else "fallback palabras clave"
        return (
            f"[Negocio] slug={decision.slug or 'sin_asignar'} metodo={decision.method}"
            f" ({quien}) confianza={confianza}: {decision.reason}"
        )

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
