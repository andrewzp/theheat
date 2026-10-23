"""Private blind A/B copy-review packs built around the existing comparison contract.

Candidates come from verified private request archives (read API v1), and their
qualification from a separately supplied operator selection. Neither capture
completeness, passing model checks nor an old prose grade is qualification.
Two candidates form a pair only on the exact same qualified evidence (bundle
identity). Origins, provenance and opaque-ID translation live only in a separate
owner-only private record; the exported review page receives display data only.

``prepare_copy_comparison``/``summarize_copy_comparison`` are reused unchanged.
No generation, provider call, automatic judge or invented quality score exists
here. A typed rater identity is an assertion, never authenticated humanity.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import json
import re
from typing import Any

from src.editorial.revisions import fingerprint
from src.evaluation.copy_comparison import (
    CopyComparisonError, prepare_copy_comparison, summarize_copy_comparison,
)
from src.two_bot.request_archive import canonical_json, sha256_hex, strict_json_loads
from src.two_bot.request_archive_replay import VerifiedArchive, lineage

SELECTION_SCHEMA = "theheat.copy-review-selection/v1"
PACK_SCHEMA = "theheat.copy-review-pack/v1"
PRIVATE_SCHEMA = "theheat.copy-review-private/v2"
BALLOT_SCHEMA = "theheat.copy-review-ballot/v1"
IMPORT_SCHEMA = "theheat.copy-review-import/v2"
MAX_SELECTION_BYTES = 8 * 1024 * 1024
MAX_BALLOT_BYTES = 2_000_000
MAX_PAIRS = 100
MAX_BALLOTS = 1_000
CLOCK_SKEW = timedelta(minutes=5)
RUBRIC = {
    "id": "theheat.copy-rubric/v1",
    "scale": "integer 1 to 5; no default; abstain may leave scores empty",
    "scores": {
        "punch": "How strongly the sentence lands. 1 = flat, 5 = sharpest.",
        "clarity": "How easily a reader gets the exact claim. 1 = confusing, 5 = clearest.",
        "unnecessary_words": "How many words could go without loss. 1 = none, 5 = many. HIGHER IS WORSE.",
    },
    "preference": "A, B, tie, or abstain. Prefer the sharper copy only if both say the same supported thing.",
    "length": "Characters and words are descriptive only; shorter is not truer or better, and not platform length.",
}
RUBRIC_SHA256 = sha256_hex(canonical_json(RUBRIC))
CLOCK_POLICY = ("rated_at is the browser clock at export, timezone-aware; import accepts "
                "pack.created_at <= rated_at <= --as-of + 5 minutes")
_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_SCOPE = re.compile(r"\Ascope-[0-9a-f]{32}\Z")
_EVIDENCE_SCOPES = ("observed", "forecast", "reanalysis", "mixed", "unknown")
_RATER_KINDS = ("human_assertion", "synthetic_fixture")


class CopyReviewError(ValueError):
    """Fixed code; never echoes candidate text, notes or origins."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CopyReviewError(code)


def _aware(value: Any, code: str) -> datetime:
    _require(type(value) is str and len(value) <= 64, code)
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CopyReviewError(code) from None
    _require(moment.utcoffset() is not None, code)
    return moment


def _text(value: Any, maximum: int, code: str) -> str:
    _require(type(value) is str and bool(value.strip()) and len(value) <= maximum, code)
    value.encode("utf-8")
    return value


# ------------------------------------------------------------- selection

def parse_selection(data: bytes) -> dict:
    """Strict operator selection: which archived candidates to compare, and why qualified."""
    _require(type(data) is bytes and len(data) <= MAX_SELECTION_BYTES, "selection_over_limit")
    try:
        raw = strict_json_loads(data)
    except (ValueError, UnicodeError):
        raise CopyReviewError("selection_json_invalid") from None
    _require(type(raw) is dict and set(raw) == {"schema", "pairs"}, "selection_shape")
    _require(raw["schema"] == SELECTION_SCHEMA, "selection_schema_version")
    _require(type(raw["pairs"]) is list and 1 <= len(raw["pairs"]) <= MAX_PAIRS, "selection_pairs")
    pairs = []
    for pair in raw["pairs"]:
        _require(type(pair) is dict and set(pair) == {"label", "evidence", "candidates"}, "selection_pair_shape")
        evidence = pair["evidence"]
        _require(type(evidence) is dict and set(evidence) == {"bundle_sha256", "qualification", "source_context",
                                                              "evidence_scope", "evidence_time"}, "evidence_shape")
        _require(type(evidence["bundle_sha256"]) is str and bool(_HEX64.fullmatch(evidence["bundle_sha256"])),
                 "evidence_bundle_sha256")
        _require(evidence["evidence_scope"] in _EVIDENCE_SCOPES, "evidence_scope")
        _aware(evidence["evidence_time"], "evidence_time")
        _text(evidence["source_context"], 8000, "source_context")
        qualification = evidence["qualification"]
        _require(type(qualification) is dict and set(qualification) == {"status", "adjudicator", "reference",
                                                                         "method"}, "qualification_shape")
        _require(type(pair["candidates"]) is list and len(pair["candidates"]) == 2, "selection_candidate_count")
        for candidate in pair["candidates"]:
            _require(type(candidate) is dict, "candidate_shape")
            kind = set(candidate) - {"factual_status", "rejection_reasons", "material_claims"}
            _require(kind in ({"archive_candidate"}, {"manual_edit"}), "candidate_shape")
            if "archive_candidate" in candidate:
                ref = candidate["archive_candidate"]
                _require(type(ref) is dict and set(ref) == {"scope_id", "candidate_text_sha256"}
                         and type(ref["scope_id"]) is str and bool(_SCOPE.fullmatch(ref["scope_id"]))
                         and type(ref["candidate_text_sha256"]) is str
                         and bool(_HEX64.fullmatch(ref["candidate_text_sha256"])), "archive_candidate_ref")
            else:
                edit = candidate["manual_edit"]
                _require(type(edit) is dict and set(edit) == {"text", "edited_from", "author_assertion"},
                         "manual_edit_shape")
                _text(edit["text"], 280, "manual_edit_text")
                _require(type(edit["author_assertion"]) is str and bool(_ID.fullmatch(edit["author_assertion"])),
                         "manual_edit_author")
                ref = edit["edited_from"]
                _require(type(ref) is dict and set(ref) == {"scope_id", "candidate_text_sha256"}
                         and type(ref["scope_id"]) is str and bool(_SCOPE.fullmatch(ref["scope_id"]))
                         and type(ref["candidate_text_sha256"]) is str
                         and bool(_HEX64.fullmatch(ref["candidate_text_sha256"])), "manual_edit_reference")
        _text(pair["label"], 200, "selection_label")
        pairs.append(pair)
    return {"schema": SELECTION_SCHEMA, "pairs": pairs, "selection_sha256": sha256_hex(data)}


def _archive_candidate(archives: dict[str, VerifiedArchive], ref: dict) -> dict | None:
    archive = archives.get(ref["scope_id"])
    if archive is None or archive.status == "invalid":
        return None
    matches = []
    for generation in lineage(archive):
        for candidate in generation["candidates"]:
            if candidate["candidate_text_sha256"] == ref["candidate_text_sha256"]:
                record = next(c for c in archive.candidates
                              if c["candidate_text_sha256"] == ref["candidate_text_sha256"])
                text = archive.artifact(record["text_artifact"]).decode("utf-8")
                matches.append({"text": text, "bundle_sha256": generation["bundle_sha256"],
                        "attempt": candidate["attempt"], "scope_id": archive.scope_id,
                        "archive_status": archive.status, "manifest_sha256": archive.manifest_sha256,
                        "model_check_outcomes": {stage: entry["outcome"] for stage, entry
                                                 in sorted(candidate["stages"].items())},
                        "terminal": generation["terminal"]})
    # A text-only reference cannot select between different generations/attempts.
    return matches[0] if len(matches) == 1 else None


def _token(seed: bytes, label: str) -> str:
    return hmac.new(seed, label.encode("utf-8"), hashlib.sha256).hexdigest()


def build_pack(selection: dict, archives: list[VerifiedArchive], *, created_at: datetime,
               seed: bytes) -> tuple[dict | None, dict, dict]:
    """Return (public_pack or None, private_record, held_report).

    The public pack carries display data only. The private record keeps the
    full comparison inputs, side assignments, origins, provenance and ID
    translation needed to restore rating bindings later.
    """
    _require(created_at.utcoffset() is not None, "created_at_not_aware")
    _require(type(seed) is bytes and len(seed) >= 16, "seed_too_short")
    by_scope = {archive.scope_id: archive for archive in archives if archive.scope_id}
    _require(all(by_scope[a.scope_id].manifest_sha256 == a.manifest_sha256
                 for a in archives if a.scope_id), "archive_scope_identity_conflict")
    pairs_input, assignments, provenance, kinds, held = [], {}, {}, {}, []
    for index, pair in enumerate(selection["pairs"]):
        reasons, resolved = [], []
        qualification = pair["evidence"]["qualification"]
        for slot, candidate in enumerate(pair["candidates"]):
            if "archive_candidate" in candidate:
                found = _archive_candidate(by_scope, candidate["archive_candidate"])
                if found is None:
                    reasons.append(f"candidate_{slot}_not_in_verified_archives")
                    continue
                resolved.append({**found, "kind": "archive_candidate", "selection": candidate})
            else:
                edit = candidate["manual_edit"]
                base = _archive_candidate(by_scope, edit["edited_from"])
                if base is None:
                    reasons.append(f"candidate_{slot}_edit_base_not_in_verified_archives")
                    continue
                resolved.append({"text": edit["text"], "bundle_sha256": base["bundle_sha256"],
                                 "attempt": None, "scope_id": base["scope_id"], "kind": "manual_edit",
                                 "archive_status": base["archive_status"],
                                 "manifest_sha256": base["manifest_sha256"],
                                 "edited_from": dict(edit["edited_from"]),
                                 "author_assertion": edit["author_assertion"],
                                 "model_check_outcomes": {}, "terminal": None, "selection": candidate})
        if len(resolved) == 2:
            if any(r["bundle_sha256"] != pair["evidence"]["bundle_sha256"] for r in resolved):
                reasons.append("candidates_not_on_the_exact_selected_evidence")
            if resolved[0]["text"] == resolved[1]["text"]:
                reasons.append("identical_text_is_not_a_comparison")
        if qualification.get("status") != "qualified" or qualification.get("method") == "not_reviewed":
            reasons.append("evidence_not_qualified_by_explicit_review")
        for slot, candidate in enumerate(pair["candidates"]):
            if candidate.get("factual_status") != "qualified":
                reasons.append(f"candidate_{slot}_not_qualified")
        if reasons:
            held.append({"selection_index": index, "label_sha256": sha256_hex(pair["label"].encode("utf-8")),
                         "reasons": sorted(set(reasons))})
            continue
        pair_id = "pair-" + _token(seed, f"pair:{index}")[:16]
        source_context = (f"{pair['evidence']['source_context']}\n\nEvidence scope: "
                          f"{pair['evidence']['evidence_scope']}. Evidence time: {pair['evidence']['evidence_time']}.")
        candidates = []
        for slot, found in enumerate(resolved):
            candidate_id = "cand-" + _token(seed, f"cand:{index}:{slot}")[:16]
            selected = found["selection"]
            origin = (f"archive:{found['scope_id']}:attempt:{found['attempt']}" if found["kind"] == "archive_candidate"
                      else f"manual_edit:{found['author_assertion']}:of:{found['edited_from']['scope_id']}")
            candidates.append({"candidate_id": candidate_id, "text": found["text"],
                               "text_sha256": sha256_hex(found["text"].encode("utf-8")), "origin": origin,
                               "factual_status": selected.get("factual_status"),
                               "rejection_reasons": selected.get("rejection_reasons", []),
                               "material_claims": selected.get("material_claims", [])})
            provenance[candidate_id] = {key: found[key] for key in (
                "kind", "scope_id", "attempt", "bundle_sha256", "archive_status", "manifest_sha256",
                "model_check_outcomes", "terminal")} | (
                {"edited_from": found["edited_from"], "author_assertion": found["author_assertion"]}
                if found["kind"] == "manual_edit" else {})
        swap = int(_token(seed, f"side:{index}")[0], 16) % 2 == 1
        first, second = (candidates[1], candidates[0]) if swap else (candidates[0], candidates[1])
        assignments[pair_id] = {"A": first["candidate_id"], "B": second["candidate_id"]}
        kinds[pair_id] = ("model_vs_manual_edit" if any(r["kind"] == "manual_edit" for r in resolved)
                          else "model_vs_model")
        pairs_input.append({"pair_id": pair_id, "evidence_sha256": pair["evidence"]["bundle_sha256"],
                            "qualification": dict(qualification), "source_context": source_context,
                            "candidates": candidates})
    private = {"schema": PRIVATE_SCHEMA, "created_at": created_at.isoformat(),
               "selection_sha256": selection["selection_sha256"], "pairs_input": pairs_input,
               "side_assignments": assignments, "pair_kinds": kinds, "provenance": provenance, "held": held,
               "archives": [{"scope_id": a.scope_id, "manifest_sha256": a.manifest_sha256, "status": a.status}
                            for a in sorted(archives, key=lambda a: a.manifest_sha256)],
               "authority": "private_origin_mapping_never_display"}
    held_report = {"schema": "theheat.copy-review-held/v1", "held_pairs": held, "eligible_pairs": len(pairs_input),
                   "result": "pack_built" if pairs_input else "held_no_pair",
                   "interpretation": "Held pairs bought nothing and fabricated no alternative."}
    if not pairs_input:
        private["pack_id"] = private["pack_sha256"] = None
        private["private_sha256"] = _identity(private, "private_sha256")
        return None, private, held_report
    public = _public_pack(pairs_input, assignments, created_at)
    private["pack_id"], private["pack_sha256"] = public["pack_id"], public["pack_sha256"]
    private["private_mapping"] = prepare_copy_comparison(pairs_input, side_assignments=assignments)["private_mapping"]
    private["private_sha256"] = _identity(private, "private_sha256")
    return public, private, held_report


def _public_pack(pairs_input: list[dict], assignments: dict, created_at: datetime) -> dict:
    prepared = prepare_copy_comparison(pairs_input, side_assignments=assignments)
    pairs = []
    for display in prepared["display_pairs"]:
        pairs.append({"pair_id": display["pair_id"], "pair_sha256": display["pair_sha256"],
                      "evidence_sha256": display["evidence_sha256"], "source_context": display["source_context"],
                      "qualification": display["qualification"],
                      "sides": {side: {"text": value["text"], "text_sha256": value["text_sha256"],
                                       "characters": value["characters"], "words": value["words"]}
                                for side, value in sorted(display["sides"].items())}})
    body = {"schema": PACK_SCHEMA, "created_at": created_at.isoformat(), "rubric": RUBRIC,
            "rubric_sha256": RUBRIC_SHA256, "clock_policy": CLOCK_POLICY, "pairs": pairs,
            "notice": "Private blind review pack. Sides are randomized; A/B are not models or methods."}
    body["pack_id"] = "pack-" + sha256_hex(canonical_json(body))[:16]
    body["pack_sha256"] = sha256_hex(canonical_json(body))
    return body


def _identity(value: dict, field: str) -> str:
    # The existing evaluator returns finite float averages in its summaries.
    body = {key: item for key, item in value.items() if key != field}
    return sha256_hex(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8"))


def verify_private_record(private: Any) -> dict:
    """Rebuild the public pack from private inputs; any edit changes its identity."""
    try:
        _require(type(private) is dict and private.get("schema") == PRIVATE_SCHEMA, "private_schema")
        _require(bool(private.get("pairs_input")) and type(private.get("pack_sha256")) is str, "private_has_no_pack")
        created = _aware(private["created_at"], "private_created_at")
        rebuilt = _public_pack(private["pairs_input"], private["side_assignments"], created)
        _require(rebuilt["pack_sha256"] == private["pack_sha256"] and rebuilt["pack_id"] == private["pack_id"],
                 "pack_changed_since_export")
        _require(private.get("private_sha256") == _identity(private, "private_sha256"), "private_record_identity_mismatch")
        prepared = prepare_copy_comparison(private["pairs_input"], side_assignments=private["side_assignments"])
        _require(private["private_mapping"] == prepared["private_mapping"], "private_mapping_mismatch")
        archives: dict[str, dict] = {}
        for archive in private["archives"]:
            _require(type(archive) is dict and set(archive) == {"scope_id", "manifest_sha256", "status"},
                     "private_archive_shape")
            _require(type(archive["manifest_sha256"]) is str and
                     (bool(_HEX64.fullmatch(archive["manifest_sha256"])) or
                      (archive["status"] == "invalid" and archive["manifest_sha256"] == "")) and
                     archive["status"] in ("complete", "incomplete", "invalid"), "private_archive_identity")
            if archive["scope_id"] is None:
                _require(archive["status"] == "invalid", "private_archive_identity")
                continue
            _require(type(archive["scope_id"]) is str and bool(_SCOPE.fullmatch(archive["scope_id"])),
                     "private_archive_identity")
            prior = archives.setdefault(archive["scope_id"], archive)
            _require(prior == archive, "private_archive_identity_conflict")
        expected_candidates, expected_kinds = set(), {}
        for pair in private["pairs_input"]:
            kinds = []
            for candidate in pair["candidates"]:
                cid = candidate["candidate_id"]
                expected_candidates.add(cid)
                record = private["provenance"][cid]
                _require(record["kind"] in ("archive_candidate", "manual_edit"), "private_candidate_kind")
                kinds.append(record["kind"])
                archive = archives.get(record["scope_id"])
                _require(archive is not None and archive["status"] != "invalid" and
                         archive["manifest_sha256"] == record["manifest_sha256"] and
                         archive["status"] == record["archive_status"] and
                         record["bundle_sha256"] == pair["evidence_sha256"], "private_provenance_mismatch")
                if record["kind"] == "archive_candidate":
                    _require(type(record["attempt"]) is int and record["attempt"] >= 1,
                             "private_candidate_attempt")
                    origin = f"archive:{record['scope_id']}:attempt:{record['attempt']}"
                else:
                    _require(record["attempt"] is None and
                             record["edited_from"]["scope_id"] == record["scope_id"], "private_manual_edit_base")
                    _require(type(record["author_assertion"]) is str and
                             bool(_ID.fullmatch(record["author_assertion"])), "private_manual_edit_author")
                    origin = f"manual_edit:{record['author_assertion']}:of:{record['scope_id']}"
                _require(candidate["origin"] == origin, "private_candidate_origin_mismatch")
            expected_kinds[pair["pair_id"]] = "model_vs_manual_edit" if "manual_edit" in kinds else "model_vs_model"
        _require(set(private["provenance"]) == expected_candidates, "private_provenance_candidates_mismatch")
        _require(private["pair_kinds"] == expected_kinds, "private_pair_kinds_mismatch")
    except CopyReviewError:
        raise
    except (CopyComparisonError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise CopyReviewError("private_inputs_invalid") from None
    return rebuilt


def pack_data_script(public: dict) -> bytes:
    """The page data as a classic script; HTML-significant characters are escaped."""
    encoded = json.dumps(public, ensure_ascii=False, sort_keys=True, allow_nan=False)
    for raw, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"),
                         (" ", "\\u2029")):
        encoded = encoded.replace(raw, escaped)
    return ("// Private review data. Display only; no origins, provenance or ID translation.\n"
            f"window.PRIVATE_COPY_REVIEW_PACK = {encoded};\n").encode("utf-8")


# ---------------------------------------------------------------- ballots

def _ballot(data: bytes, pack: dict, as_of: datetime) -> tuple[dict | None, str | None]:
    if type(data) is not bytes or len(data) > MAX_BALLOT_BYTES:
        return None, "ballot_over_limit"
    try:
        raw = strict_json_loads(data)
    except (ValueError, UnicodeError):
        return None, "ballot_json_invalid"
    expected = {"schema", "pack_id", "pack_sha256", "rubric_id", "rubric_sha256", "rater_id", "rater_kind",
                "rater_assertion", "rated_at", "ratings", "form_version"}
    if type(raw) is not dict or set(raw) != expected:
        return None, "ballot_shape"
    if raw["schema"] != BALLOT_SCHEMA:
        return None, "ballot_schema_version"
    if raw["form_version"] != "1":
        return None, "ballot_form_version"
    if raw["pack_id"] != pack["pack_id"] or raw["pack_sha256"] != pack["pack_sha256"]:
        return None, "ballot_for_another_or_changed_pack"
    if raw["rubric_id"] != RUBRIC["id"] or raw["rubric_sha256"] != RUBRIC_SHA256:
        return None, "ballot_rubric_mismatch"
    if type(raw["rater_id"]) is not str or not _ID.fullmatch(raw["rater_id"]):
        return None, "ballot_rater_id"
    if raw["rater_kind"] not in _RATER_KINDS or raw["rater_assertion"] is not True:
        return None, "ballot_rater_assertion"
    try:
        rated = _aware(raw["rated_at"], "ballot_clock")
    except CopyReviewError:
        return None, "ballot_clock_invalid_or_naive"
    if not datetime.fromisoformat(pack["created_at"]) <= rated <= as_of + CLOCK_SKEW:
        return None, "ballot_clock_outside_policy"
    if type(raw["ratings"]) is not list or len(raw["ratings"]) > len(pack["pairs"]):
        return None, "ballot_ratings_shape"
    return raw, None


def import_ballots(private: dict, ballots: list[bytes], *, as_of: datetime) -> dict:
    """Restore bindings for exported ballots and run the existing summarizer.

    Duplicate identical ratings collapse; conflicting ones are quarantined;
    stale/forged/invalid ratings are kept as separate outcomes. Synthetic
    fixture ballots are summarized separately and add zero human ratings.
    """
    _require(as_of.utcoffset() is not None, "as_of_not_aware")
    _require(len(ballots) <= MAX_BALLOTS, "too_many_ballots")
    pack = verify_private_record(private)
    pairs = {pair["pair_id"]: pair for pair in pack["pairs"]}
    mapping = private["private_mapping"]
    outcomes: list[dict[str, Any]] = []
    candidates: list[tuple[str, dict]] = []
    for data in ballots:
        ballot, error = _ballot(data, pack, as_of)
        digest = sha256_hex(data) if type(data) is bytes else None
        if ballot is None:
            outcomes.append({"ballot_sha256": digest, "outcome": "rejected", "reason": error})
            continue
        accepted = 0
        for index, item in enumerate(ballot["ratings"]):
            reason = None
            if type(item) is not dict or set(item) != {"pair_id", "pair_sha256", "scores", "preference", "notes"}:
                reason = "rating_shape"
            elif type(item["pair_id"]) is not str or item["pair_id"] not in pairs:
                reason = "rating_unknown_pair"
            elif item["pair_sha256"] != pairs[item["pair_id"]]["pair_sha256"]:
                reason = "rating_stale_pair_binding"
            if reason is None:
                rating = {"binding": mapping[item["pair_id"]]["rating_binding"], "rater_id": ballot["rater_id"],
                          "rated_at": ballot["rated_at"], "scores": item["scores"],
                          "preference": item["preference"], "notes": item["notes"]}
                try:
                    summarize_copy_comparison(private["pairs_input"], side_assignments=private["side_assignments"],
                                              ratings=[rating])
                except CopyComparisonError:
                    reason = "rating_rejected_by_existing_contract"
            if reason is not None:
                outcomes.append({"ballot_sha256": digest, "outcome": "rating_refused", "rating_index": index,
                                 "reason": reason})
                continue
            accepted += 1
            _require(len(candidates) < MAX_BALLOTS, "too_many_ratings")
            candidates.append((ballot["rater_kind"], rating))
        outcomes.append({"ballot_sha256": digest, "outcome": "ballot_read", "rater_kind": ballot["rater_kind"],
                         "ratings_offered": len(ballot["ratings"]), "ratings_valid": accepted})
    offered = [{"kind": kind, "rating": rating} for kind, rating in candidates]
    derived = _summaries(private, offered)
    report = {"schema": IMPORT_SCHEMA, "pack_id": pack["pack_id"], "pack_sha256": pack["pack_sha256"],
              "private_sha256": private["private_sha256"],
              "as_of": as_of.isoformat(), "clock_policy": CLOCK_POLICY, "rubric_sha256": RUBRIC_SHA256,
              "ballots": outcomes, "offered_ratings": offered, **derived,
              "pair_kinds": private["pair_kinds"],
              "interpretation": {
                  "synthetic_fixture_summary": "synthetic_fixture_ballots_are_not_human_preference",
                  "rater_identity": "typed_assertion_not_authenticated",
                  "model_vs_manual_edit": "a_manual_edit_preference_is_not_a_model_A_B_result",
                  "display_sides": "A/B are randomized display sides, not models or methods",
                  "publication_approved": False}}
    report["report_sha256"] = _identity(report, "report_sha256")
    return report


def _summaries(private: dict, offered: list[dict]) -> dict:
    _require(type(offered) is list and len(offered) <= MAX_BALLOTS, "offered_ratings_shape")
    grouped: dict[tuple, list[tuple[str, dict]]] = {}
    for item in offered:
        _require(type(item) is dict and set(item) == {"kind", "rating"} and item["kind"] in _RATER_KINDS,
                 "offered_rating_shape")
        kind, rating = item["kind"], item["rating"]
        summarize_copy_comparison(private["pairs_input"], side_assignments=private["side_assignments"], ratings=[rating])
        grouped.setdefault((rating["binding"]["pair_id"], rating["rater_id"]), []).append((kind, rating))
    kept: dict[str, list[dict]] = {kind: [] for kind in _RATER_KINDS}
    retries, conflicts = 0, []
    for (pair_id, rater_id), entries in sorted(grouped.items()):
        prints = {fingerprint({"kind": kind, "rating": rating}) for kind, rating in entries}
        if len(prints) > 1:
            conflicts.append({"pair_id": pair_id, "rater_id": rater_id, "ratings": len(entries),
                              "outcome": "conflicting_ratings_quarantined"})
            continue
        retries += len(entries) - 1
        kind, rating = entries[0]
        kept[kind].append(rating)
    summaries = {kind: summarize_copy_comparison(private["pairs_input"], side_assignments=private["side_assignments"],
                                                 ratings=ratings) for kind, ratings in kept.items()}
    return {"identical_retries_collapsed": retries, "conflicts": conflicts,
            "human_asserted_summary": summaries["human_assertion"],
            "synthetic_fixture_summary": summaries["synthetic_fixture"],
            "real_human_ratings_added": summaries["human_assertion"]["unique_rating_count"]}


def verify_import_report(report: Any, private: dict, *, as_of: datetime) -> dict:
    """Verify retained report identity, exact private lineage and reconstructed ratings.

    This authenticates no rater. Offered ratings retain their asserted/synthetic
    class and go through the unchanged evaluator again before a downstream join.
    """
    pack = verify_private_record(private)
    _require(as_of.utcoffset() is not None, "as_of_not_aware")
    try:
        _require(type(report) is dict and report.get("schema") == IMPORT_SCHEMA, "import_report_schema")
        _require(report.get("report_sha256") == _identity(report, "report_sha256"), "import_report_identity_mismatch")
        _require(report["pack_id"] == pack["pack_id"] and report["pack_sha256"] == pack["pack_sha256"] and
                 report["private_sha256"] == private["private_sha256"] and
                 report["pair_kinds"] == private["pair_kinds"], "import_report_lineage_mismatch")
        imported_at = _aware(report["as_of"], "import_report_clock")
        _require(imported_at <= as_of and report["clock_policy"] == CLOCK_POLICY and
                 report["rubric_sha256"] == RUBRIC_SHA256, "import_report_clock_or_rubric")
        for item in report["offered_ratings"]:
            rated = _aware(item["rating"]["rated_at"], "import_rating_clock")
            _require(_aware(pack["created_at"], "private_created_at") <= rated <= imported_at + CLOCK_SKEW,
                     "import_rating_clock_outside_policy")
        derived = _summaries(private, report["offered_ratings"])
        _require(all(report[key] == value and fingerprint(report[key]) == fingerprint(value)
                     for key, value in derived.items()), "import_report_summary_mismatch")
        _require(report["interpretation"]["publication_approved"] is False and
                 report["interpretation"]["rater_identity"] == "typed_assertion_not_authenticated" and
                 report["interpretation"]["synthetic_fixture_summary"] ==
                 "synthetic_fixture_ballots_are_not_human_preference", "import_report_interpretation")
    except CopyReviewError:
        raise
    except (CopyComparisonError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise CopyReviewError("import_report_invalid") from None
    return report
