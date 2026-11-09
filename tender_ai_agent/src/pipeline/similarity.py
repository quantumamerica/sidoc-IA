"""Deteccion de la misma oportunidad publicada con otra URL, otro titulo o sin plazo.

Los agregadores (cleat.ai, developmentaid, highergov, procuretap...) copian el aviso oficial con
el titulo en otra caja, con el codigo agregado ("RFP 27-017AG"), con sufijos ("| CLEATUS") o
truncado ("Consultoria para el fortalecimiento de la ..."), y muchas veces sin plazo. La
comparacion exacta de titulo + plazo + organismo no los ve, asi que se compara por palabras:
si casi todas las palabras del titulo mas corto estan en el otro y los plazos no se contradicen,
es la misma oportunidad.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from urllib.parse import urlparse

# Palabras que no distinguen un aviso de otro.
STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "to", "in", "on", "at", "by", "with", "or",
    "de", "del", "la", "las", "el", "los", "y", "e", "en", "para", "por", "con", "un", "una",
    "do", "da", "dos", "das", "o", "os", "as", "para", "le", "les", "des", "du", "et", "pour",
    "rfp", "rfq", "rfi", "eoi", "reoi", "request", "proposal", "proposals", "quotation",
    "open", "tender", "tenders", "bid", "bids", "notice", "cleatus", "highergov", "procuretap",
    "developmentaid", "starbridge", "tenderhive", "lightrfp", "easytenders", "view",
}
TRUNCATION_MARKERS = ("...", "…")
CONTAINMENT_THRESHOLD = 0.8
MIN_TOKENS = 4
# Por debajo de esta cantidad de palabras el titulo es generico ("Cost of Service and Rate
# Consulting Services") y se exige que los organismos no se contradigan.
SHORT_TITLE_TOKENS = 7
DEADLINE_TOLERANCE_DAYS = 10


def _strip_accents(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))


def _words(text: str | None) -> list[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", _strip_accents(text).lower())


def is_truncated(title: str | None) -> bool:
    return bool(title) and title.strip().endswith(TRUNCATION_MARKERS)


def _slug_words(url: str | None) -> list[str]:
    if not url:
        return []
    path = urlparse(url).path.rstrip("/")
    last = path.rsplit("/", 1)[-1] if path else ""
    words = _words(last.replace("-", " ").replace("_", " "))
    # El slug de un titulo truncado tambien viene cortado: la ultima palabra puede estar a medias.
    return words[:-1] if len(words) > 1 else words


def title_tokens(title: str | None, url: str | None = None) -> set[str]:
    words = _words(title)
    if is_truncated(title):
        words = words + _slug_words(url)
    return {word for word in words if word not in STOPWORDS and len(word) > 1}


# Codigo de la convocatoria escrito en el titulo: "RFP 27-017AG", "B260316", "WB-OP00459459".
# Tiene que mezclar letras y digitos, o digitos con guion, para no confundirlo con un anio o un numero suelto.
SOLICITATION_CODE = re.compile(r"\b(?=[a-z0-9-]*\d)(?:[a-z]{1,4}-?\d{4,}[a-z0-9-]*|\d{2,4}-\d{2,}[a-z0-9-]*)\b")

# "2026", "2026-2030" o "2026-27" son anios o periodos, no codigos.
YEAR_OR_RANGE = re.compile(r"(19|20)\d{2}(-((19|20)?\d{2}))?")


def solicitation_codes(title: str | None) -> set[str]:
    if not title:
        return set()
    text = _strip_accents(title).lower()
    return {code.strip("-") for code in SOLICITATION_CODE.findall(text) if not YEAR_OR_RANGE.fullmatch(code)}


def _deadlines_compatible(left: date | None, right: date | None) -> bool:
    if left is None or right is None:
        return True
    return abs((left - right).days) <= DEADLINE_TOLERANCE_DAYS


def _authorities_conflict(left: str | None, right: str | None) -> bool:
    left_words = set(_words(left)) - STOPWORDS
    right_words = set(_words(right)) - STOPWORDS
    if not left_words or not right_words:
        return False
    if left_words & right_words:
        return False
    left_text = " ".join(sorted(left_words))
    right_text = " ".join(sorted(right_words))
    # Siglas parecidas (IADB / IDB) cuentan como el mismo organismo.
    return SequenceMatcher(None, left_text, right_text).ratio() < 0.6


def looks_like_same_opportunity(
    title_a: str | None,
    title_b: str | None,
    *,
    deadline_a: date | None = None,
    deadline_b: date | None = None,
    authority_a: str | None = None,
    authority_b: str | None = None,
    url_a: str | None = None,
    url_b: str | None = None,
) -> bool:
    # El mismo codigo de convocatoria en los dos titulos, del mismo organismo y con plazos que no se
    # contradicen, es la misma oportunidad aunque un agregador reescriba el resto ("BESS" por
    # "Battery Energy Storage System").
    if (
        solicitation_codes(title_a) & solicitation_codes(title_b)
        and _deadlines_compatible(deadline_a, deadline_b)
        and not _authorities_conflict(authority_a, authority_b)
    ):
        return True
    tokens_a = title_tokens(title_a, url_a)
    tokens_b = title_tokens(title_b, url_b)
    smaller, larger = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    if len(smaller) < MIN_TOKENS:
        return False
    containment = len(smaller & larger) / len(smaller)
    if containment < CONTAINMENT_THRESHOLD:
        return False
    if not _deadlines_compatible(deadline_a, deadline_b):
        return False
    if len(smaller) < SHORT_TITLE_TOKENS and _authorities_conflict(authority_a, authority_b):
        return False
    return True

