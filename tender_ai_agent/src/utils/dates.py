from __future__ import annotations

import re
from datetime import date, datetime, timezone


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
