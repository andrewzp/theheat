"""Deterministic copy gates for the current editorial direction.

Andrew's direction (28-30 October 2026): one complete sentence by default, the
strongest supported fact first, no sterile source-led opener, no generic
explanatory ending, no invented danger and no padding toward 280 characters.

These rules are free, local and conservative. They only *reject* a few
unmistakable shapes before any paid check is bought; a clean result is never an
editorial, factual or safety pass, and nothing here rewrites, grades or ranks
text. ``dashboard/lib/copy-gates.js`` mirrors the bundle-blind rules for the
editor's advisory notes; the paired vectors in
``tests/fixtures/copy_gate_vectors.json`` keep both sides identical.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

COPY_GATES_VERSION = "copy-gates-v1"
MAX_EXCERPT = 80

# Free blocking codes. Advisory codes never block a draft.
BLOCKING = ("source_led_opener", "generic_explanatory_ending", "too_many_sentences", "invented_danger")
ADVISORY = ("second_sentence", "over_automatic_length", "danger_wording_needs_source", "consequence_needs_review")
MESSAGES = {
    "source_led_opener": "Lead with the place and the fact, not the source, model or product; attribution and forecast labels follow the fact.",
    "generic_explanatory_ending": "End on the fact or a sourced consequence; a generic reminder/highlighting/climate ending adds words without news.",
    "too_many_sentences": "One complete sentence is the default; a second only for essential qualification or a sourced consequence.",
    "invented_danger": "Danger or health wording needs the same wording in an attributed source warning; none is supplied.",
    "second_sentence": "A second sentence must be essential qualification or a sourced consequence.",
    "over_automatic_length": "Over 200 characters: cannot post automatically; shorter usually reads better.",
    "danger_wording_needs_source": "Danger or health wording needs an attributed source warning saying so.",
    "consequence_needs_review": "Check this diagnostic or consequence clause against the source; it may be substantive rather than filler.",
}

_I = re.IGNORECASE | re.ASCII
_URL = re.compile(r"https?://\S+", _I)
_SOURCE_PHRASE_OPENER = re.compile(
    r"^(?:according\s+to|per|via|citing|data\s+from|figures\s+from|readings\s+from|"
    r"new\s+data\s+from|satellite\s+data\s+from)\b", _I)
_ARTICLE_SOURCE_OPENER = re.compile(
    r"^(?:an?|the|new|latest|today's|this\s+week's)\s+"
    r"(?:[A-Za-z0-9][A-Za-z0-9_.'/-]*\s+){0,4}?"
    r"(?:models?|forecasts?|analysis|reanalysis|dataset|data|product|bulletin|advisory|"
    r"outlook|estimates?|readings?|observations?|measurements?)\s+"
    r"(?:now\s+)?(?:puts?|shows?|showed|has|have|places?|projects?|indicates?|suggests?|says|"
    r"finds|found|estimates?|forecasts?|predicts?|reports?|reported|flags?|flagged|records?|"
    r"recorded|registers?|registered|detects?|detected|calls\s+for|warns?|warned)\b", _I)
_NAMED_SOURCE_OPENER = re.compile(
    r"^(?:CAMS|Copernicus|ERA5|ECMWF|GFS|GHCN(?:d|-Daily)?|FIRMS|MODIS|VIIRS|IMERG|GPM|NASA|"
    r"NOAA|NWS|NHC|JTWC|JMA|GDACS|USGS|NSIDC|FEMA|WMO|Open-Meteo|Meteostat|Coral\s+Reef\s+Watch|"
    r"CRW|HMS|AEMET|IMD|SAWS|Met\s+Office|BoM|DWD|KMA|CMA|PAGASA)(?:'s)?(?=[\s:,.]|$)", re.ASCII)

_ENDING_REMINDER = re.compile(
    r"(?:[,;:]|\s-{1,2}|\s—|—|\s–)\s*(?:an?|another|the\s+latest)\s+"
    r"(?:[A-Za-z-]+\s+){0,2}?(?:reminder|sign|signal|testament|illustration|example|symbol|"
    r"snapshot|glimpse|wake-up\s+call)\s+(?:of|that|to)\b[^.!?]*[.!?]?\s*$", _I)
_ENDING_REMINDER_SENTENCE = re.compile(
    r"(?:^|[.!?]\s+)(?:it's|it\s+is|this\s+is|that's|that\s+is|another|a)\s+"
    r"(?:[A-Za-z-]+\s+){0,2}?(?:reminder|sign|signal|testament|illustration|example|symbol|"
    r"wake-up\s+call)\s+(?:of|that|to)\b[^.!?]*[.!?]?\s*$", _I)
_ENDING_PARTICIPLE = re.compile(
    r"(?:[,;:]|\s-{1,2}|\s—|—|\s–)\s*(?:highlighting|underscoring|underlining|"
    r"illustrating|demonstrating|showcasing|emphasi[sz]ing|signall?ing\s+(?:a|the|how|that)|"
    r"raising\s+concerns?)\b[^.!?]*[.!?]?\s*$", _I)
_ENDING_CLIMATE = re.compile(
    r"\bas\s+(?:the\s+|our\s+)?(?:climate|planet|world|earth|globe)\s+(?:warms|heats(?:\s+up)?|"
    r"changes|keeps\s+warming|continues\s+to\s+warm)\b[^.!?]*[.!?]?\s*$", _I)
_CLIMATE_SLOGAN = re.compile(
    r"\b(?:climate\s+change|global\s+warming)\s+(?:in\s+action|is\s+here|is\s+real|at\s+work)\b", _I)
_WINK_KICKER = re.compile(
    r"(?:^|[.!?]\s+)(?:the\s+calendar\s+says\s+[A-Za-z]+|and\s+it's\s+only\s+[A-Za-z]+|"
    r"a\s+record\s+is\s+a\s+record|let\s+that\s+sink\s+in|read\s+that\s+again|"
    r"you\s+read\s+that\s+right)[.!?]?\s*$", _I)
_DIAGNOSTIC = re.compile(r"\b(?:sign|signal|testament|illustration|example|symbol|snapshot|glimpse)\s+(?:of|that|to)\b", _I)
_GENERIC_CONTEXT = re.compile(r"\b(?:warming\s+world|region\s+is\s+warming|growing\s+heat\s+risk|climate\s+change|changing\s+climate)\b", _I)

_DANGER = re.compile(
    r"\b(?:life[-\s]threatening|dangerous(?:ly)?|deadly|lethal|hazardous|unhealthy|unsafe|toxic|"
    r"potentially\s+fatal|fatal|health\s+(?:risk|threat|hazard|emergency)|threat\s+to\s+life|"
    r"threatens?\s+lives|brace\s+for)\b", _I)

# Conservative sentence boundary: terminal punctuation, optional closing quote or
# bracket, whitespace, then a capital letter or digit. Known abbreviations and
# single initials never end a sentence.
_BOUNDARY = re.compile(r"[.!?][\"')\]]*\s+(?=[A-Z0-9\"'(])", re.ASCII)
_ABBREVIATIONS = frozenset({
    "st", "mt", "ft", "no", "vs", "approx", "est", "dr", "jr", "sr", "inc", "co", "corp", "gov",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "a.m", "p.m", "u.s", "u.k", "u.n", "e.g", "i.e", "etc",
})


@dataclass(frozen=True)
class CopyNote:
    code: str
    blocking: bool
    excerpt: str

    @property
    def message(self) -> str:
        return MESSAGES[self.code]

    def to_dict(self) -> dict:
        return {"code": self.code, "blocking": self.blocking, "excerpt": self.excerpt,
                "message": self.message}


_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def visible_copy(text: str) -> str:
    """The prose a reader sees: source URLs removed, quotes and spacing normalized."""
    return " ".join(_URL.sub(" ", text).translate(_QUOTES).split())


def sentences(text: str) -> list[str]:
    body = visible_copy(text)
    result: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(body):
        stop = match.start() + 1
        words = body[start:stop - 1].split()
        token = words[-1].lstrip("(\"'").lower() if words else ""
        if token in _ABBREVIATIONS or (len(token) == 1 and token.isascii() and token.isalpha()):
            continue
        result.append(body[start:stop].strip())
        start = match.end()
    tail = body[start:].strip()
    if tail:
        result.append(tail)
    return result


def _excerpt(value: str) -> str:
    value = " ".join(value.split())
    return value if len(value) <= MAX_EXCERPT else value[:MAX_EXCERPT - 1] + "…"


def _source_text(bundle: Any) -> str | None:
    """Current event's explicit source prose, never arbitrary serialized metadata.

    This is only a cheap absence/wording aid. Presence is not factual approval;
    uncertain paraphrases still require every existing model/factual check.
    """
    if bundle is None:
        return None
    try:
        value = bundle.to_dict() if hasattr(bundle, "to_dict") else bundle
    except (TypeError, ValueError, AttributeError):
        return ""

    if not isinstance(value, dict):
        return ""
    excerpts = []
    for fact in value.get("current_facts", []):
        if not isinstance(fact, dict) or fact.get("label") not in {
                "warning_text", "forecast_hazard_statement", "source_reported_context", "report_statement"}:
            continue
        if fact.get("event_id", value.get("event_id")) != value.get("event_id"):
            continue
        if isinstance(fact.get("value"), str) and fact.get("source_url") and fact.get("source_name"):
            excerpts.append(fact["value"])
    raw = value.get("raw_signal_dump")
    if isinstance(raw, dict) and isinstance(raw.get("warning_text"), str):
        excerpts.append(raw["warning_text"])
    return " ".join(excerpts).lower()


def _danger_support(term: str, source: str) -> tuple[bool, bool]:
    """Word-bound matches and narrow explicit negation, never a semantic pass.

    'Without warning' and 'no evacuations' do not negate a danger assertion.
    Ambiguous paraphrases remain for the mandatory factual/safety checks.
    """
    def normalize(text: str) -> str:
        return re.sub(r"[-\s]+", " ", text.lower()).replace("dangerously", "dangerous")
    wanted, supported, negated = normalize(term), False, False
    for sentence in re.split(r"[.!?;\n]", source):
        normalized = normalize(sentence)
        for match in re.finditer(r"\b" + re.escape(wanted) + r"\b", normalized):
            prefix, suffix = normalized[:match.start()], normalized[match.end():]
            denied = bool(re.search(r"\b(?:no|not|never|without)\s+(?:[a-z]+\s+){0,2}$", prefix)
                          and not re.search(r"\bnot\s+only\s*$", prefix))
            denied = denied or bool(re.match(r"\s+(?:[a-z]+\s+){0,3}(?:not|never)\s+expected\b", suffix))
            negated |= denied
            supported |= not denied
    return supported, negated and not supported


def copy_notes(text: str, bundle: Any = None) -> list[CopyNote]:
    """Every copy note for ``text``; ``bundle=None`` makes danger wording advisory."""
    if not isinstance(text, str):
        return []
    body = visible_copy(text)
    if not body:
        return []
    notes: list[CopyNote] = []
    for pattern in (_SOURCE_PHRASE_OPENER, _NAMED_SOURCE_OPENER, _ARTICLE_SOURCE_OPENER):
        match = pattern.search(body)
        if match:
            notes.append(CopyNote("source_led_opener", True, _excerpt(match.group(0))))
            break
    for pattern in (_ENDING_REMINDER, _ENDING_REMINDER_SENTENCE, _ENDING_PARTICIPLE,
                    _ENDING_CLIMATE, _CLIMATE_SLOGAN, _WINK_KICKER):
        match = pattern.search(body)
        if match:
            ambiguous = bool(_DIAGNOSTIC.search(match.group(0)) and not _GENERIC_CONTEXT.search(match.group(0)))
            notes.append(CopyNote("consequence_needs_review" if ambiguous else "generic_explanatory_ending", not ambiguous,
                                  _excerpt(match.group(0).lstrip(" ,;:.!?-—–"))))
            break
    parts = sentences(body)
    if len(parts) >= 3:
        notes.append(CopyNote("too_many_sentences", True, _excerpt(parts[2])))
    elif len(parts) == 2:
        notes.append(CopyNote("second_sentence", False, _excerpt(parts[1])))
    source = _source_text(bundle)
    for match in _DANGER.finditer(body):
        term = re.sub(r"[-\s]+", " ", match.group(0).lower())
        if source is None:
            notes.append(CopyNote("danger_wording_needs_source", False, _excerpt(match.group(0))))
            break
        supported, negated = _danger_support(term, source)
        if not supported:
            # Missing wording in an actual warning is semantic uncertainty, not
            # proof that a synonymous consequence was invented. Mandatory checks
            # decide it. With no current-event warning at all, reject free.
            uncertain = bool(source.strip()) and not negated
            notes.append(CopyNote("danger_wording_needs_source" if uncertain else "invented_danger",
                                  not uncertain, _excerpt(match.group(0))))
            break
    if len(text) > 200:  # Unicode scalars of the complete text, as the automatic cap counts.
        notes.append(CopyNote("over_automatic_length", False, f"{len(text)} characters"))
    return notes


def copy_rejection(text: str, bundle: Any = None) -> str | None:
    """The first blocking note as ``code: excerpt``, or None. None is not a pass."""
    for note in copy_notes(text, bundle):
        if note.blocking:
            return f"{note.code}: {note.excerpt!r}"
    return None
