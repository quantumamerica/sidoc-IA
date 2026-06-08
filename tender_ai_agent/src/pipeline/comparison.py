from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

from models.schemas import MappedOpportunity, ProviderComparisonResult, ProviderRunReport

try:
    from rapidfuzz import fuzz
except ImportError:  # Permite que el proyecto compile antes de instalar requirements.
    fuzz = None


TITLE_STRONG_MATCH = 92
TITLE_SIMILAR_MATCH = 86


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None

    parsed = urlsplit(cleaned)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    normalized = "".join(character.lower() if character.isalnum() else " " for character in title)
    return " ".join(normalized.split())


def _similarity(left: str | None, right: str | None) -> float:
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if fuzz is not None:
        return float(fuzz.token_set_ratio(left_norm, right_norm))
    return SequenceMatcher(None, left_norm, right_norm).ratio() * 100


def _same_text(left: str | None, right: str | None) -> bool:
    return normalize_title(left) == normalize_title(right) and bool(normalize_title(left))


def _deadline(value: MappedOpportunity) -> date | None:
    return value.deadline


def are_same_opportunity(a: MappedOpportunity, b: MappedOpportunity) -> bool:
    url_a = normalize_url(a.official_url or a.url)
    url_b = normalize_url(b.official_url or b.url)
    if url_a and url_b and url_a == url_b:
        return True

    if a.referencia and b.referencia and _same_text(a.referencia, b.referencia):
        return True

    title_score = _similarity(a.titulo_estudio or a.raw_title, b.titulo_estudio or b.raw_title)
    same_deadline = _deadline(a) is not None and _deadline(a) == _deadline(b)
    same_authority = _same_text(a.organismo_contratado or a.contracting_authority, b.organismo_contratado or b.contracting_authority)
    same_country = _same_text(a.country or a.ambito_geografico, b.country or b.ambito_geografico)

    if title_score >= TITLE_STRONG_MATCH and same_authority and same_deadline:
        return True
    if title_score >= TITLE_SIMILAR_MATCH and same_country and same_deadline:
        return True
    return False


def merge_opportunities(a: MappedOpportunity, b: MappedOpportunity) -> MappedOpportunity:
    primary, secondary = _choose_primary(a, b)
    payload = deepcopy(primary.model_dump())
    secondary_payload = secondary.model_dump()

    for key, value in secondary_payload.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value

    providers = sorted(
        {
            provider
            for provider in [
                getattr(a.provider, "value", a.provider),
                getattr(b.provider, "value", b.provider),
                "openai",
                "perplexity",
            ]
            if provider
        }
    )
    payload["metadata"] = {**(a.metadata or {}), **(b.metadata or {}), "providers": providers}
    payload["evidence_urls"] = _unique((a.evidence_urls or []) + (b.evidence_urls or []))
    payload["audit_notes"] = _unique(
        (a.audit_notes or [])
        + (b.audit_notes or [])
        + [f"Merge cross-provider: providers={providers}"]
    )

    raw_paths = _unique([path for path in [a.raw_response_path, b.raw_response_path] if path])
    if raw_paths:
        payload["metadata"]["raw_response_paths"] = raw_paths

    deadline_a = _deadline(a)
    deadline_b = _deadline(b)
    if deadline_a and deadline_b and deadline_a != deadline_b:
        payload["requires_human_review"] = True
        payload["audit_notes"].append(
            f"Conflicto de deadline entre proveedores: {deadline_a.isoformat()} vs {deadline_b.isoformat()}"
        )
    elif deadline_a:
        payload["deadline"] = deadline_a
    elif deadline_b:
        payload["deadline"] = deadline_b

    url_a = a.official_url or a.url
    url_b = b.official_url or b.url
    payload["official_url"] = _best_url(url_a, url_b)
    if normalize_url(url_a) and normalize_url(url_b) and normalize_url(url_a) != normalize_url(url_b):
        if not (_is_official_url(url_a) or _is_official_url(url_b)):
            payload["requires_human_review"] = True
            payload["audit_notes"].append("Conflicto de URL sin fuente claramente oficial; requiere revision humana.")
        else:
            payload["audit_notes"].append(f"Conflicto de URL resuelto priorizando fuente oficial: {payload['official_url']}")
    payload["url"] = payload["official_url"] or payload.get("url")
    return MappedOpportunity.model_validate(payload)


def compare_provider_results(
    openai_results: list[MappedOpportunity],
    perplexity_results: list[MappedOpportunity],
    *,
    run_id: str = "",
) -> ProviderComparisonResult:
    service = ProviderComparisonService()
    result, _ = service.compare_opportunities(
        run_id=run_id,
        openai_items=openai_results,
        perplexity_items=perplexity_results,
    )
    return result


class ProviderComparisonService:
    def compare(self, reports: list[ProviderRunReport]) -> dict[str, Any]:
        by_provider: dict[str, dict[str, int | float | None]] = defaultdict(dict)
        for report in reports:
            provider_key = report.provider.value
            current = by_provider.setdefault(
                provider_key,
                {
                    "raw_responses": 0,
                    "candidates": 0,
                    "eligible": 0,
                    "valid": 0,
                    "mapped": 0,
                    "inserted": 0,
                    "rejected": 0,
                    "cost_estimate_usd": None,
                },
            )
            for field in ["raw_responses", "candidates", "eligible", "valid", "mapped", "inserted", "rejected"]:
                current[field] = int(current[field] or 0) + int(getattr(report, field))
            if report.cost_estimate_usd is not None:
                current["cost_estimate_usd"] = float(current["cost_estimate_usd"] or 0) + report.cost_estimate_usd
        return {"providers": dict(by_provider)}

    def compare_opportunities(
        self,
        *,
        run_id: str,
        openai_items: list[MappedOpportunity],
        perplexity_items: list[MappedOpportunity],
    ) -> tuple[ProviderComparisonResult, list[MappedOpportunity]]:
        matched_openai: set[int] = set()
        matched_perplexity: set[int] = set()
        found_by_both: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        merged: list[MappedOpportunity] = []
        all_merged_for_audit: list[MappedOpportunity] = []

        for openai_index, openai_item in enumerate(openai_items):
            match_index = self._find_match(openai_item, perplexity_items, matched_perplexity)
            if match_index is None:
                continue
            perplexity_item = perplexity_items[match_index]
            matched_openai.add(openai_index)
            matched_perplexity.add(match_index)
            merged_item = merge_opportunities(openai_item, perplexity_item)
            all_merged_for_audit.append(merged_item)
            match_key = self._key(merged_item)
            found_by_both.append(
                {
                    "key": match_key,
                    "openai": self._summary(openai_item),
                    "perplexity": self._summary(perplexity_item),
                    "merged": self._summary(merged_item),
                }
            )
            if merged_item.requires_human_review:
                conflicts.append(
                    {
                        "key": match_key,
                        "type": "needs_review",
                        "reason": "conflict_detected_during_merge",
                        "audit_notes": merged_item.audit_notes,
                    }
                )
            else:
                merged.append(merged_item)

        openai_only_items = [item for index, item in enumerate(openai_items) if index not in matched_openai]
        perplexity_only_items = [item for index, item in enumerate(perplexity_items) if index not in matched_perplexity]

        merged.extend(openai_only_items)
        merged.extend(perplexity_only_items)

        result = ProviderComparisonResult(
            run_id=run_id,
            providers={
                "openai": {"count": len(openai_items)},
                "perplexity": {"count": len(perplexity_items)},
            },
            found_by_both=found_by_both,
            openai_only=[self._summary(item) for item in openai_only_items],
            perplexity_only=[self._summary(item) for item in perplexity_only_items],
            only_openai=[self._key(item) for item in openai_only_items],
            only_perplexity=[self._key(item) for item in perplexity_only_items],
            common=[item["key"] for item in found_by_both],
            conflicts=conflicts,
            merged_opportunities=[item.model_dump(mode="json") for item in all_merged_for_audit + openai_only_items + perplexity_only_items],
        )
        return result, merged

    def final_deduplicate(self, opportunities: list[MappedOpportunity]) -> tuple[list[MappedOpportunity], list[MappedOpportunity]]:
        seen: set[str] = set()
        unique: list[MappedOpportunity] = []
        duplicates: list[MappedOpportunity] = []
        for opportunity in opportunities:
            key = self._key(opportunity)
            if key in seen:
                duplicates.append(opportunity)
                continue
            seen.add(key)
            unique.append(opportunity)
        return unique, duplicates

    @staticmethod
    def _key(opportunity: MappedOpportunity) -> str:
        url = normalize_url(opportunity.official_url or opportunity.url)
        if url:
            return url
        if opportunity.referencia:
            return f"ref:{normalize_title(opportunity.referencia)}"
        return "|".join(
            [
                opportunity.organismo_contratado or "",
                opportunity.titulo_estudio or "",
                str(opportunity.deadline or ""),
                opportunity.referencia or "",
            ]
        ).lower()

    @staticmethod
    def _find_match(item: MappedOpportunity, candidates: list[MappedOpportunity], used_indexes: set[int]) -> int | None:
        for index, candidate in enumerate(candidates):
            if index in used_indexes:
                continue
            if are_same_opportunity(item, candidate):
                return index
        return None

    @staticmethod
    def _summary(item: MappedOpportunity) -> dict[str, Any]:
        return {
            "key": ProviderComparisonService._key(item),
            "provider": getattr(item.provider, "value", item.provider),
            "title": item.titulo_estudio,
            "authority": item.organismo_contratado,
            "country": item.country or item.ambito_geografico,
            "deadline": item.deadline.isoformat() if item.deadline else None,
            "url": item.official_url or item.url,
            "requires_human_review": item.requires_human_review,
        }


def _choose_primary(a: MappedOpportunity, b: MappedOpportunity) -> tuple[MappedOpportunity, MappedOpportunity]:
    score_a = _evidence_score(a)
    score_b = _evidence_score(b)
    return (a, b) if score_a >= score_b else (b, a)


def _evidence_score(item: MappedOpportunity) -> int:
    score = 0
    if item.official_url or item.url:
        score += 4
    if item.evidence_urls:
        score += min(len(item.evidence_urls), 4)
    if item.evidence_text:
        score += 2
    if item.deadline:
        score += 2
    if item.referencia:
        score += 1
    return score


def _best_url(left: str | None, right: str | None) -> str | None:
    urls = [url for url in [left, right] if url]
    if not urls:
        return None
    official_domains = (".gov", ".gob", ".org", ".int", ".europa.eu", "worldbank.org", "iadb.org", "adb.org", "afdb.org", "ebrd.com")
    ranked = sorted(
        urls,
        key=lambda url: (
            any(domain in url.lower() for domain in official_domains),
            len(url),
        ),
        reverse=True,
    )
    return ranked[0]


def _is_official_url(url: str | None) -> bool:
    if not url:
        return False
    official_domains = (
        ".gov",
        ".gob",
        ".org",
        ".int",
        ".europa.eu",
        "worldbank.org",
        "iadb.org",
        "adb.org",
        "afdb.org",
        "ebrd.com",
    )
    lowered = url.lower()
    return any(domain in lowered for domain in official_domains)


def _unique(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
