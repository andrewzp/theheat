"""Private, advisory diagnosis of the copy the bot actually saved; offline and read-only.

Inputs are explicit local JSON exports (a state snapshot with ``drafts`` and optional
``suppressions``, or a bare list of drafts), read through ``file_boundary`` (no symlink,
device or FIFO; bounded). Nothing is fetched, discovered, executed, rewritten or approved.

The report distinguishes recorded stages and never upgrades them: a missing record is
``unknown``, a recorded failure is activity (not zero), and a saved draft is not a post. A
``posted`` status with a recorded tweet id is reported as a recorded receipt, not as verified X
visibility. Text measures and warnings are deterministic and advisory with stated parser limits;
the report makes no factual verdict, model-quality score, preference, engagement or invoice claim.
Exact texts appear only in the private review sheet, never in the summary returned to stdout.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any

SCHEMA = "theheat.observed-copy-report/v2"
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_INPUTS = 16
MAX_DRAFTS = 5000


class ReportError(ValueError):
    """A supplied export cannot be used; the report is not produced."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _refuse_constant(name: str):
    raise ReportError("input_non_finite_number")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ReportError("input_non_finite_number")
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ReportError("input_duplicate_key")
        result[key] = value
    return result


@dataclass(frozen=True)
class Export:
    label: str
    sha256: str
    drafts: list
    suppressions: list | None
    draft_pointer_prefix: str = "/drafts"


def parse_export(label: str, raw: bytes) -> Export:
    """Validate one export's shape; fail visibly instead of guessing."""
    if len(raw) > MAX_INPUT_BYTES:
        raise ReportError("input_size_limit")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_refuse_constant,
                          parse_float=_finite_float, object_pairs_hook=_unique_object)
    except ReportError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ReportError("input_not_json") from exc
    try:
        _canonical(data).encode("utf-8")
        label.encode("utf-8")
    except UnicodeError as exc:
        raise ReportError("input_invalid_string") from exc
    drafts: list
    suppressions: list | None = None
    prefix = "/drafts"
    if isinstance(data, list):
        drafts = data
        prefix = ""
    elif isinstance(data, dict) and isinstance(data.get("drafts"), list):
        drafts = data["drafts"]
        suppressions = data.get("suppressions")
        if suppressions is not None and not isinstance(suppressions, list):
            raise ReportError("suppression_history_invalid")
    else:
        raise ReportError("input_has_no_draft_list")
    if len(drafts) > MAX_DRAFTS:
        raise ReportError("input_too_many_drafts")
    for draft in drafts:
        if not isinstance(draft, dict) or not isinstance(draft.get("id"), str) or not draft["id"]:
            raise ReportError("draft_without_identity")
        if not isinstance(draft.get("text"), str):
            raise ReportError("draft_without_text")
    for row in suppressions or []:
        if not isinstance(row, dict):
            raise ReportError("suppression_without_object")
        identity, stage = row.get("id"), row.get("stage")
        if identity not in (None, "") and (not isinstance(identity, str)
                or not identity.strip() or len(identity) > 256
                or any(ord(c) < 32 for c in identity)):
            raise ReportError("suppression_invalid_identity")
        if stage is not None and (not isinstance(stage, str) or len(stage) > 128
                                 or any(ord(c) < 32 for c in stage)):
            raise ReportError("suppression_invalid_stage")
    return Export(label=label, sha256=_sha(raw), drafts=drafts,
                  suppressions=suppressions, draft_pointer_prefix=prefix)


# --- deterministic text measures ------------------------------------------------------------------

URL = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
_ABBREVIATIONS = ("U.S.", "U.K.", "a.m.", "p.m.", "e.g.", "i.e.", "approx.", "vs.", "Mt.", "St.", "No.", "Jan.", "Feb.",
                  "Mar.", "Apr.", "Aug.", "Sept.", "Sep.", "Oct.", "Nov.", "Dec.")
_DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")
_SENTENCE_END = re.compile(r"[.!?](?:[\"'”’)]*)(?=\s+[\"'“‘(]*[A-Z0-9−-]|\s*$)")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
_MONTH = r"(?:" + "|".join(m[:3] + r"(?:" + m[3:] + r")?\.?" for m in MONTHS) + r")"
_DATE = re.compile(rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+{_MONTH}|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?)\b"
                   r"|\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|yesterday|today)\b", re.IGNORECASE)
_MEASURE = re.compile(r"[−-]?\d+(?:[.,]\d+)?\s?(?:°\s?[CF]\b|mm\b|cm\b|in\b|inches\b|%|km\b|mph\b|km/h\b|m\b|kt\b|knots\b|hPa\b|µg/m³)")
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,}\b")
_SOURCE_LEAD = re.compile(r"^\W*(?:NWS|NOAA|GHCN|ERA5|AEMET|NASA|USGS|GDACS|CAMS|C3S|AWC|METAR|NHC|JTWC|FIRMS|IMD|SAWS)\b")
_QUALIFIERS = re.compile(r"\b(?:available|accepted|preliminary|provisional|sampled|according to|data show|reported|"
                         r"estimated|unofficial|at least)\b", re.IGNORECASE)
OBSERVED_TYPES = frozenset({"observed"})


def body_of(text: str) -> str:
    return URL.sub("", text).strip()


def sentence_count(text: str) -> int:
    """Count sentences in the body. Limits: protects URLs, decimals, listed abbreviations and dates;
    an unlisted abbreviation followed by a capital is over-counted, and a missing final stop is one sentence."""
    body = body_of(text)
    if not body:
        return 0
    masked = _DECIMAL.sub("·", body)
    for abbreviation in _ABBREVIATIONS:
        masked = masked.replace(abbreviation, abbreviation.replace(".", "·"))
    ends = len(_SENTENCE_END.findall(masked))
    return max(1, ends + (0 if re.search(r"[.!?][\"'”’)]*\s*$", masked) else 1))


def warnings_for(text: str, *, observed: bool | None) -> list[str]:
    body = body_of(text)
    found = []
    lead = " ".join(body.split()[:6])
    if _SOURCE_LEAD.search(body) or len(_ACRONYM.findall(lead)) >= 2:
        found.append("source_or_acronym_lead")
    dates = [match.group(0).lower().rstrip(".") for match in _DATE.finditer(body)]
    if len(dates) != len(set(dates)):
        found.append("repeated_date")
    if len({match.group(0).replace(" ", "") for match in _MEASURE.finditer(body)}) >= 4:
        found.append("many_competing_numbers")
    if len(_QUALIFIERS.findall(body)) >= 3:
        found.append("stacked_qualifiers")
    urls = URL.findall(text)
    if urls and sum(len(url) for url in urls) * 2 > len(text):
        found.append("source_url_dominates_text")
    if observed is True and not dates:
        found.append("no_explicit_observation_date")
    return found


# --- recorded stages -------------------------------------------------------------------------------

def _two_bot(draft: dict) -> dict:
    context = draft.get("review_context")
    two_bot = context.get("two_bot") if isinstance(context, dict) else None
    return two_bot if isinstance(two_bot, dict) else {}


def _bundle(draft: dict) -> dict:
    bundle = _two_bot(draft).get("bundle")
    return bundle if isinstance(bundle, dict) else {}


def _evidence_type(draft: dict) -> str | None:
    raw = _bundle(draft).get("raw_signal_dump")
    evidence = raw.get("evidence") if isinstance(raw, dict) else None
    kind = evidence.get("evidence_type") if isinstance(evidence, dict) else None
    return kind if isinstance(kind, str) else None


def stages(draft: dict) -> dict:
    two_bot = _two_bot(draft)
    accepted = two_bot.get("accepted_writer_observation")
    generation = ("recorded" if isinstance(accepted, dict) or draft.get("writer_observations") or draft.get("candidates")
                  else "unknown")
    fact = two_bot.get("fact_check")
    fact_check = ("unknown" if not isinstance(fact, dict) or not isinstance(fact.get("passed"), bool)
                  else "passed" if fact["passed"] else "failed")
    critic = two_bot.get("critic")
    verdict = critic.get("verdict") if isinstance(critic, dict) else None
    raw_status = draft.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in {
        "pending", "approved", "rejected", "posted", "suppressed", "parked"} else "unknown"
    outcome, tweet_id = draft.get("publish_outcome"), draft.get("tweet_id")
    if outcome in ("unknown", "submitted"):
        publication = "unknown"
    elif status == "posted":
        receipt = isinstance(tweet_id, str) and bool(tweet_id.strip())
        publication = "recorded_receipt" if receipt else "status_posted_without_receipt"
    elif outcome not in (None, "not_sent") or tweet_id:
        publication = "unknown"
    elif status in {"pending", "approved", "rejected", "suppressed", "parked"}:
        publication = "no_publication_recorded"
    else:
        publication = "unknown"
    join = "unjoined"
    if isinstance(accepted, dict) and isinstance(accepted.get("text_sha256"), str):
        join = "final_equals_accepted_writer_output" if accepted["text_sha256"] == _sha(draft["text"]) else \
            "final_differs_from_accepted_writer_output"
    return {"generation": generation, "fact_check": fact_check,
            "critic": verdict if isinstance(verdict, str) and verdict in {"PASS", "REVISE", "KILL"}
            else "unknown", "save": "saved", "status": status, "publication": publication,
            "writer_to_saved": join}


# --- report -----------------------------------------------------------------------------------------

def _pointer(export: Export, index: int, argument: int) -> dict:
    return {"input": export.label, "input_sha256": export.sha256,
            "argument_index": argument, "pointer": f"{export.draft_pointer_prefix}/{index}"}


_SUPPRESSION_STAGES = frozenset({
    "score_gate", "writer", "safety", "honesty_gate", "evidence_contract",
    "evidence_readiness", "fact_check", "critic", "budget_exhausted",
    "pipeline_error", "triage_cap", "triage_error", "cycle_cap", "source",
    "source_scope", "automatic_policy", "automatic_eligibility", "model_preflight",
    "preflight", "billing", "billing_pause", "duplicate", "cooldown", "unknown",
})


def _retained_suppressions(exports: list[Export]) -> dict:
    """Declared row IDs and anonymous capture/index rows, never attempt IDs."""
    identified: dict[str, dict] = {}
    anonymous: dict[tuple[str, int], dict] = {}
    available, unavailable = set(), set()
    supplied = 0
    for argument, export in enumerate(exports):
        if export.suppressions is None:
            unavailable.add(export.sha256)
            continue
        available.add(export.sha256)
        supplied += len(export.suppressions)
        for index, row in enumerate(export.suppressions):
            pointer = {"input": export.label, "input_sha256": export.sha256,
                       "argument_index": argument, "pointer": f"/suppressions/{index}"}
            digest = _sha(_canonical(row))
            if row.get("id"):
                entry = identified.setdefault(row["id"], {"variants": {}, "pointers": []})
                entry["variants"].setdefault(digest, row)
                entry["pointers"].append(pointer)
            else:
                entry = anonymous.setdefault((export.sha256, index),
                                             {"row": row, "row_sha256": digest, "pointers": []})
                entry["pointers"].append(pointer)
    included, conflicts = [], []
    for identity in sorted(identified):
        entry = identified[identity]
        if len(entry["variants"]) != 1:
            conflicts.append({"id_sha256": _sha(identity), "variants": len(entry["variants"]),
                              "pointers": entry["pointers"]})
            continue
        [(digest, row)] = entry["variants"].items()
        included.append({"identity_kind": "declared_suppression_id", "id_sha256": _sha(identity),
                         "row_sha256": digest, "pointers": entry["pointers"], "row": row})
    for key in sorted(anonymous):
        included.append({"identity_kind": "anonymous_export_row", **anonymous[key]})
    counts: Counter = Counter()
    rows = []
    for entry in included:
        stage = entry["row"].get("stage")
        # A source's arbitrary stage string is not a safe stdout label or proof
        # of a model failure. Preserve its row hash/pointers, classify it unknown.
        stage = stage if stage in _SUPPRESSION_STAGES else "unknown"
        counts[stage] += 1
        rows.append({k: v for k, v in entry.items() if k != "row"} | {"stage": stage})
    return {"availability": "partial_or_unavailable" if unavailable else "retained_lists_supplied",
            "counts_scope": "retained_rows_not_generation_or_paid_attempts",
            "exports_with_retained_list": len(available), "exports_without_history": len(unavailable),
            "supplied_rows": supplied, "identified_ids": len(identified),
            "identified_rows_included": len(identified) - len(conflicts),
            "anonymous_rows_included": len(anonymous), "conflicting_ids_held": len(conflicts),
            "stage_counts": dict(sorted(counts.items())), "rows": rows, "conflicts": conflicts,
            "unique_failed_generations": None, "paid_attempts": None}


def build_report(exports: list[Export]) -> tuple[dict, str, str]:
    """Return (summary JSON, summary Markdown, private review sheet Markdown)."""
    if not exports or len(exports) > MAX_INPUTS:
        raise ReportError("input_count_out_of_range")
    seen: dict[str, dict] = {}
    for argument, export in enumerate(exports):
        for index, draft in enumerate(export.drafts):
            entry = seen.setdefault(draft["id"], {"variants": {}, "pointers": []})
            entry["variants"].setdefault(_sha(_canonical(draft)), draft)
            entry["pointers"].append(_pointer(export, index, argument))
    included, conflicts = [], []
    for draft_id in sorted(seen):
        entry = seen[draft_id]
        if len(entry["variants"]) > 1:
            conflicts.append({"id_sha256": _sha(draft_id), "variants": len(entry["variants"]), "pointers": entry["pointers"]})
        else:
            [draft] = entry["variants"].values()
            included.append((draft, entry["pointers"]))

    rows = []
    for draft, pointers in included:
        text = draft["text"]
        observed = _evidence_type(draft)
        rows.append({
            "id_sha256": _sha(draft["id"]), "kind": draft.get("type") if isinstance(draft.get("type"), str) else "unknown",
            "evidence_type": observed or "unknown", "text_sha256": _sha(text), "length": len(text),
            "body_length": len(body_of(text)), "urls": len(URL.findall(text)), "sentences": sentence_count(text),
            "stages": stages(draft),
            "warnings": warnings_for(text, observed=None if observed is None else observed in OBSERVED_TYPES),
            "pointers": pointers,
        })
    def count(key, field=None):
        return dict(sorted(Counter((row[key][field] if field else row[key]) for row in rows).items()))

    sentence_bins = Counter("1" if row["sentences"] == 1 else "2" if row["sentences"] == 2 else "3+" for row in rows)
    summary = {
        "schema": SCHEMA, "advisory_only": True,
        "inputs": [{"argument_index": argument, "label": export.label, "sha256": export.sha256,
                    "drafts": len(export.drafts),
                    "suppressions": None if export.suppressions is None else len(export.suppressions)}
                   for argument, export in enumerate(exports)],
        "identities": {"supplied_records": sum(len(export.drafts) for export in exports), "distinct_ids": len(seen),
                       "included": len(included), "conflicting_held_and_excluded": len(conflicts)},
        "conflicts": conflicts,
        "stages": {name: count("stages", name) for name in
                   ("generation", "fact_check", "critic", "status", "publication", "writer_to_saved")},
        "retained_suppressions": _retained_suppressions(exports),
        "length": {"max": max((row["length"] for row in rows), default=0),
                   "over_200": sum(row["length"] > 200 for row in rows),
                   "with_source_url": sum(row["urls"] > 0 for row in rows)},
        "sentences": dict(sorted(sentence_bins.items())),
        "warnings": dict(sorted(Counter(code for row in rows for code in row["warnings"]).items())),
        "drafts": rows,
        "limits": [
            "Stages are only what the export records: missing is unknown, failed is activity, saved is not published.",
            "A recorded tweet id is a stored receipt, not verified X visibility or engagement.",
            "Sentence counts protect URLs, decimals, listed abbreviations and dates; other abbreviations may over-count.",
            "Warnings are lexical prompts for a human editor, not factual or quality verdicts.",
            "Suppression rows are retained activity, not unique failed generations or paid attempts; missing history is unavailable.",
            "No publication recorded is not proof of nonpublication; unresolved or contradictory delivery stays unknown.",
        ],
    }
    return summary, _markdown(summary), _review_sheet(included)


def _markdown(summary: dict) -> str:
    ids = summary["identities"]
    lines = ["# Observed-copy report (private, advisory)", "",
             f"Inputs: {len(summary['inputs'])}. Records supplied: {ids['supplied_records']}; distinct ids "
             f"{ids['distinct_ids']}; included {ids['included']}; conflicting held and excluded "
             f"{ids['conflicting_held_and_excluded']}.", ""]
    for name, values in summary["stages"].items():
        lines.append(f"- {name}: " + ", ".join(f"{key} {value}" for key, value in values.items()))
    retained = summary["retained_suppressions"]
    lines += ["", "Retained suppression rows (not unique failed generations or paid attempts): " +
              (", ".join(f"{k} {v}" for k, v in retained["stage_counts"].items()) or "no included retained rows"),
              f"Suppression history: {retained['exports_with_retained_list']} exports with retained lists; "
              f"{retained['exports_without_history']} unavailable; {retained['conflicting_ids_held']} conflicting IDs held.",
              f"Sentences: {summary['sentences']}. Length: {summary['length']}.",
              f"Warnings: {summary['warnings'] or 'none'}.", "", "## Limits", ""]
    lines += [f"- {limit}" for limit in summary["limits"]]
    return "\n".join(lines) + "\n"


def _review_sheet(included: list) -> str:
    lines = ["# Private review sheet (nonblind editorial notes; source truth not verified)", "",
             "Each row shows unverified retained bundle fields and what the copy says. The reader-value "
             "line is an editor's nonblind judgment to be filled in, never a computed score.", ""]
    for draft, pointers in included:
        bundle = _bundle(draft)
        retained_facts = bundle.get("current_facts")
        facts = [f"{row.get('label')}: {row.get('value')}" for row in
                 (retained_facts if isinstance(retained_facts, list) else [])
                 if isinstance(row, dict) and row.get("label") and row.get("value") not in (None, "")][:8]
        lines += [f"## {draft.get('type') or 'unknown kind'} · {_sha(draft['id'])[:12]} · {draft.get('status') or 'unknown'}",
                  f"- Evidence pointer: {pointers[0]['input']} {pointers[0]['pointer']} (input sha256 {pointers[0]['input_sha256'][:16]}…)",
                  f"- Retained bundle says (unverified): {'; '.join(facts) if facts else 'no retained source facts in this export (unknown)'}",
                  f"- Copy says: {draft['text']}",
                  "- Why a reader should care (editor, nonblind): ____", ""]
    return "\n".join(lines) + "\n"
