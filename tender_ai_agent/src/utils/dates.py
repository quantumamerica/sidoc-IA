from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone


DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
)

DATE_SNIPPET_PATTERNS = (
    re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"),
    re.compile(r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b"),
)


def today_utc_date() -> date:
    return datetime.now(timezone.utc).date()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    cleaned = _clean_date_text(value)
    if not cleaned:
        return None

    parsed = _parse_clean_date(cleaned)
    if parsed:
        return parsed

    for snippet in _date_snippets(cleaned):
        parsed = _parse_clean_date(snippet)
        if parsed:
            return parsed

    return None


def _clean_date_text(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    cleaned = re.sub(r"(\d)([A-Za-z])", r"\1 \2", cleaned)
    cleaned = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.;")


def _parse_clean_date(cleaned: str) -> date | None:
    normalized = cleaned.replace(",", "")
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue

    return None


def _date_snippets(value: str) -> list[str]:
    snippets: list[str] = []
    for pattern in DATE_SNIPPET_PATTERNS:
        snippets.extend(match.group(0) for match in pattern.finditer(value))
    return snippets


def is_future_date(value: date | datetime | str | None, reference_date: date | None = None) -> bool:
    normalized = normalize_date(value)
    if normalized is None:
        return False
    return normalized > (reference_date or today_utc_date())


AMBIGUOUS_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s*$")


def possible_dates(value: date | datetime | str | None) -> list[date]:
    """Fechas posibles para un valor. "10/03/2026" puede ser 10-mar (dd/mm) o 3-oct (mm/dd, EE. UU.)."""
    normalized = normalize_date(value)
    if normalized is None:
        return []
    candidates = [normalized]
    if isinstance(value, str):
        match = AMBIGUOUS_NUMERIC_DATE.match(value)
        if match:
            first, second, year = (int(part) for part in match.groups())
            try:
                swapped = date(year, first, second)
            except ValueError:
                swapped = None
            if swapped and swapped != normalized:
                candidates.append(swapped)
    return candidates


def deadline_still_open(
    value: date | datetime | str | None,
    *,
    grace_days: int = 0,
    reference_date: date | None = None,
) -> bool:
    """True si el deadline no vencio, con margen de grace_days y aceptando la lectura dd/mm o mm/dd.

    Evita descartar como vencidas oportunidades con fecha en formato de EE. UU. o publicadas en otra
    zona horaria. Un valor que no se puede leer como fecha devuelve False.
    """
    reference = (reference_date or today_utc_date()) - timedelta(days=max(grace_days, 0))
    return any(candidate >= reference for candidate in possible_dates(value))
