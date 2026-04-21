from __future__ import annotations

"""Editorial ranking for competing tweet candidates."""

from dataclasses import dataclass
import re

from src.editorial._util import clamp as _clamp


YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
UNIT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:F|C|ppm|MW|ft|m)\b", re.IGNORECASE)
ALL_CAPS_RE = re.compile(r"\b[A-Z]{2,}\b")
MONTH_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b",
    re.IGNORECASE,
)

CATEGORY_HINTS = {
    "record": ("record", "since", "today"),
    "record_low": ("record", "since", "low"),
    "country_high": ("country", "national", "record"),
    "country_low": ("country", "national", "record"),
    "fire": ("satellite", "confidence", "MW"),
    "fire_footprint": ("hectares", "burned", "complex"),
    "co2_milestone": ("Mauna Loa", "280", "ppm"),
    "severe_weather": ("warning", "issued", "for"),
    "global_disaster": ("GDACS", "alert", "severity"),
    "sea_ice_record": ("sea ice", "satellite", "record"),
    "drought": ("drought", "extreme", "exceptional"),
    "enso": ("ENSO", "NOAA", "ONI"),
    "extreme_wave": ("wave", "feet", "meters"),
    "storm_surge": ("predicted", "water level", "above"),
    "river_flood": ("flood stage", "gauge", "above"),
    "hot10": ("today", "anomaly", "normal"),
    "marine_heatwave": ("ocean", "record", "consecutive"),
    "ice_mass_record": ("GRACE", "gigatons", "ice"),
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().strip('"').strip("'")


def _sentence_fragments(text: str) -> list[str]:
    parts = re.split(r"[.!?]+", text)
    return [part.strip() for part in parts if part.strip()]


@dataclass(frozen=True)
class CandidateScore:
    clarity: int
    context: int
    voice: int
    punch: int
    total: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "clarity": self.clarity,
            "context": self.context,
            "voice": self.voice,
            "punch": self.punch,
            "total": self.total,
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class DraftCandidate:
    rank: int
    text: str
    source: str
    score: CandidateScore

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "text": self.text,
            "source": self.source,
            "score": self.score.as_dict(),
        }


@dataclass(frozen=True)
class CandidateBundle:
    category: str
    candidates: list[DraftCandidate]

    @property
    def text(self) -> str:
        return self.candidates[0].text if self.candidates else ""

    @property
    def selected_score(self) -> CandidateScore | None:
        return self.candidates[0].score if self.candidates else None


def score_candidate_text(text: str, category: str) -> CandidateScore:
    normalized = _normalize_text(text)
    sentences = _sentence_fragments(normalized)
    sentence_count = len(sentences)
    word_count = len(re.findall(r"\b[\w']+\b", normalized))
    avg_sentence_words = word_count / max(sentence_count, 1)
    number_count = len(NUMBER_RE.findall(normalized))
    unit_hits = len(UNIT_RE.findall(normalized))
    caps_hits = len(ALL_CAPS_RE.findall(normalized))
    short_fragments = sum(1 for sentence in sentences if len(sentence.split()) <= 4)
    year_hits = len(YEAR_RE.findall(normalized))
    month_hit = bool(MONTH_RE.search(normalized))

    clarity = 42
    if 85 <= len(normalized) <= 210:
        clarity += 26
    elif 60 <= len(normalized) <= 240:
        clarity += 18
    elif len(normalized) <= 280:
        clarity += 10
    if 2 <= sentence_count <= 4:
        clarity += 18
    elif sentence_count == 1:
        clarity += 8
    if avg_sentence_words <= 13:
        clarity += 10
    if normalized.endswith("."):
        clarity += 4

    context = 32 + min(number_count, 4) * 8 + min(unit_hits, 3) * 7 + min(year_hits, 2) * 6
    if month_hit:
        context += 6
    for hint in CATEGORY_HINTS.get(category, ()):
        if hint.lower() in normalized.lower():
            context += 8

    voice = 36 + min(caps_hits, 2) * 9 + min(short_fragments, 2) * 10
    if "?" not in normalized and "!" not in normalized:
        voice += 8
    if sentence_count >= 2:
        voice += 6
    if "It's " in normalized or "That " in normalized or "Except it's" in normalized:
        voice += 6

    punch = 34 + min(number_count, 4) * 6 + min(short_fragments, 2) * 8
    if len(normalized) <= 180:
        punch += 16
    elif len(normalized) <= 220:
        punch += 10
    if any(token in normalized.lower() for token in ("first time", "new record", "lowest", "highest", "above normal")):
        punch += 8

    clarity = _clamp(clarity)
    context = _clamp(context)
    voice = _clamp(voice)
    punch = _clamp(punch)
    total = _clamp(0.30 * clarity + 0.28 * context + 0.22 * voice + 0.20 * punch)

    reasons = []
    if context >= 80:
        reasons.append("strong factual context")
    if voice >= 75:
        reasons.append("deadpan voice lands")
    if punch >= 75:
        reasons.append("clean punchy cadence")
    if clarity >= 80:
        reasons.append("easy to parse fast")

    return CandidateScore(
        clarity=clarity,
        context=context,
        voice=voice,
        punch=punch,
        total=total,
        reasons=tuple(reasons[:3]) or ("solid candidate structure",),
    )


def rank_candidates(
    candidates: list[tuple[str, str]] | list[str],
    category: str,
) -> CandidateBundle:
    ranked: list[DraftCandidate] = []
    seen: set[str] = set()

    for item in candidates:
        if isinstance(item, tuple):
            text, source = item
        else:
            text, source = item, "unknown"

        normalized = _normalize_text(text)
        if not normalized:
            continue

        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        ranked.append(
            DraftCandidate(
                rank=0,
                text=normalized,
                source=source,
                score=score_candidate_text(normalized, category),
            )
        )

    ranked = sorted(
        ranked,
        key=lambda candidate: (
            candidate.score.total,
            candidate.score.punch,
            candidate.score.context,
            -len(candidate.text),
        ),
        reverse=True,
    )

    reranked = [
        DraftCandidate(
            rank=index + 1,
            text=candidate.text,
            source=candidate.source,
            score=candidate.score,
        )
        for index, candidate in enumerate(ranked)
    ]
    return CandidateBundle(category=category, candidates=reranked)
