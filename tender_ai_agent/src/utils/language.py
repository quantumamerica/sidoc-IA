"""Idioma de una oportunidad: normaliza lo que declara el buscador y, si no declara, lo estima del texto.

Lo usa la elegibilidad para descartar avisos que no estan en los idiomas que trabaja QUANTUM.
"""
from __future__ import annotations

import re
import unicodedata

# Nombres y codigos que devuelven los modelos ("English", "en-US", "ingles", "Portugues (Brasil)").
_LANGUAGE_NAMES: dict[str, str] = {
    "es": "es", "spa": "es", "spanish": "es", "espanol": "es", "castellano": "es", "espagnol": "es",
    "espanhol": "es",
    "en": "en", "eng": "en", "english": "en", "ingles": "en", "anglais": "en",
    "pt": "pt", "por": "pt", "portuguese": "pt", "portugues": "pt", "portugais": "pt",
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr", "frances": "fr", "francais": "fr",
    "de": "de", "deu": "de", "ger": "de", "german": "de", "aleman": "de", "deutsch": "de", "allemand": "de",
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    "nl": "nl", "dutch": "nl", "neerlandes": "nl", "holandes": "nl", "nederlands": "nl",
    "pl": "pl", "polish": "pl", "polaco": "pl", "polski": "pl",
    "ro": "ro", "romanian": "ro", "rumano": "ro",
    "ru": "ru", "russian": "ru", "ruso": "ru",
    "uk": "uk", "ukrainian": "uk", "ucraniano": "uk",
    "ar": "ar", "arabic": "ar", "arabe": "ar",
    "zh": "zh", "chinese": "zh", "chino": "zh",
    "ja": "ja", "japanese": "ja", "japones": "ja",
    "ko": "ko", "korean": "ko", "coreano": "ko",
    "tr": "tr", "turkish": "tr", "turco": "tr",
    "sr": "sr", "serbian": "sr", "serbio": "sr",
    "ka": "ka", "georgian": "ka", "georgiano": "ka",
    "el": "el", "greek": "el", "griego": "el",
    "sv": "sv", "swedish": "sv", "sueco": "sv",
    "no": "no", "nb": "no", "norwegian": "no", "noruego": "no",
    "da": "da", "danish": "da", "danes": "da",
    "fi": "fi", "finnish": "fi", "fines": "fi",
    "id": "id", "indonesian": "id", "indonesio": "id",
    "vi": "vi", "vietnamese": "vi", "vietnamita": "vi",
    "th": "th", "thai": "th", "tailandes": "th",
}

# Palabras frecuentes y propias de cada idioma (sin tildes). Se evitan las que comparten varios
# idiomas ("de", "la", "en") para que el conteo no confunda espanol, frances y portugues.
_STOPWORDS: dict[str, set[str]] = {
    "es": {"el", "los", "las", "del", "para", "por", "con", "y", "servicios", "consultoria", "estudio",
           "contratacion", "licitacion", "electrica", "una", "sobre"},
    "en": {"the", "of", "and", "for", "to", "with", "services", "consulting", "consultancy", "study",
           "request", "proposals", "tender", "notice", "provision"},
    "pt": {"da", "do", "dos", "das", "e", "em", "para", "servicos", "contratacao", "estudo", "energia",
           "nao", "uma", "sobre", "licitacao", "eletrica"},
    "fr": {"le", "les", "des", "du", "et", "pour", "sur", "etude", "avis", "appel", "offres", "prestations",
           "recrutement", "cabinet", "electricite"},
    "de": {"der", "die", "das", "und", "fur", "von", "mit", "zur", "zum", "des", "im", "ausschreibung",
           "beratung", "leistungen", "dienstleistungen", "vergabe"},
    "it": {"di", "della", "delle", "dei", "il", "per", "servizi", "gara", "affidamento", "studio", "energia",
           "procedura", "aperta"},
    "nl": {"het", "van", "een", "voor", "met", "aanbesteding", "diensten", "opdracht", "onderzoek"},
    "pl": {"i", "w", "na", "z", "dla", "oraz", "usługi", "uslugi", "przetarg", "zamowienie", "dostawa"},
    "ro": {"si", "pentru", "in", "din", "servicii", "achizitie", "studiu", "privind"},
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def normalize_language(value: str | None) -> str | None:
    """Codigo ISO 639-1 de lo que declara el buscador, o None si no se reconoce."""
    if not value:
        return None
    text = _strip_accents(str(value)).strip().lower()
    if not text:
        return None
    for part in re.split(r"[\s/,;|()+&]+", text):
        if not part:
            continue
        base = part.split("-")[0].split("_")[0]
        if base in _LANGUAGE_NAMES:
            return _LANGUAGE_NAMES[base]
    return None


def declared_languages(value: str | None) -> set[str]:
    """Todos los idiomas reconocibles en el valor declarado ("es/en" -> {"es", "en"})."""
    if not value:
        return set()
    text = _strip_accents(str(value)).strip().lower()
    found: set[str] = set()
    for part in re.split(r"[\s/,;|()+&]+", text):
        base = part.split("-")[0].split("_")[0]
        if base in _LANGUAGE_NAMES:
            found.add(_LANGUAGE_NAMES[base])
    return found


def non_latin_ratio(text: str | None) -> float:
    """Fraccion de letras que no son del alfabeto latino (arabe, cirilico, chino, etc.)."""
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return 0.0
    non_latin = sum(1 for ch in letters if "LATIN" not in unicodedata.name(ch, ""))
    return non_latin / len(letters)


def guess_language(text: str | None) -> str | None:
    """Estimacion por palabras frecuentes. Devuelve None si el texto no alcanza para decidir."""
    if not text:
        return None
    if non_latin_ratio(text) > 0.5:
        return "non_latin"
    words = [_strip_accents(word.lower()) for word in _WORD.findall(text)]
    if len(words) < 4:
        return None
    counts = {lang: sum(1 for word in words if word in vocab) for lang, vocab in _STOPWORDS.items()}
    best = max(counts, key=lambda lang: counts[lang])
    if counts[best] < 2:
        return None
    runner_up = max(count for lang, count in counts.items() if lang != best)
    if counts[best] == runner_up:
        return None
    return best
