"""Text normalization used for comparison only. Displayed values are never altered."""

import re
import unicodedata

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
})
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def clean(text: str) -> str:
    """NFKC, straight quotes, unified dashes, collapsed whitespace. Case and punctuation kept."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return _WS.sub(" ", text).strip()


def normalize(text: str) -> str:
    """Comparison form: clean(), casefold, punctuation removed (apostrophes dropped, others to space)."""
    text = clean(text).casefold().replace("'", "")
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def normalize_whitespace(text: str) -> str:
    """For the government warning: only whitespace, line breaks and line-end hyphenation change."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # "imp-\nairs" -> "impairs"
    return _WS.sub(" ", text).strip()
