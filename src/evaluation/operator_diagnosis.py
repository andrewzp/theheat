"""Connected private diagnosis: archives, reconciliation, copy review and receipts.

One explicit aware ``as_of`` clock. Every component is verified (versions,
identities, original hashes) and joined only through exact lineage: archive
manifests named by the reconciliation and copy-review records, and published
receipts whose text AND bundle identity both equal an archived candidate's.
Anything else is shown as a separate row, never assigned to a likely candidate.

Dispositions are mechanical (missing response, unknown send, invalid model
output schema, missing usage, unresolved billing match, evidence changed). No
root cause, weather diagnosis or quality grade is invented. Missing optional
inputs are absent, never zero. Weekly promotion stays HOLD. Default views are
content-free; exact copy only leaves through an explicit private export.
"""
from __future__ import annotations

from datetime import datetime
import html
import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from typing import Any

from src.editorial.revisions import fingerprint
from src.evaluation import archive_usage, invoice_evidence, private_copy_pack
from src.two_bot.request_archive import (
    ROUTES, SCHEMA_V2, RequestArchiveRefused, read_private_file, require_private_directory, sha256_hex,
    strict_json_loads, write_private_file_exclusive,
)
from src.two_bot.request_archive_replay import VerifiedArchive, lineage, route_lineage

SCHEMA = "theheat.private-diagnosis/v1"
COMPONENTS = ("diagnosis.json", "diagnosis.md", "diagnosis.html")
# Views are re-rendered during verification; a renderer change is a new version, not tampering.
VIEW_RENDERER = "theheat.private-diagnosis-views/v2"
MARKER = "diagnosis.complete.json"
MAX_READER_OUTPUT = 16 * 1024 * 1024
MAX_REPORT_COMPONENT_BYTES = 64 * 1024 * 1024
# Explicit operator configuration only: no executable, home or profile discovery.
NODE = os.environ.get("THEHEAT_DIAGNOSIS_NODE", "")
READER_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/private_review_inputs.mjs"
# Fixed phrases the pipeline's own code writes for invalid model output (not model text).
_SCHEMA_PHRASES = {"writer": ("writer returned invalid JSON across", "Writer output contract rejected"),
                   "fact_check": ("fact-checker returned invalid JSON across", "Fact-check output contract rejected"),
                   "critic": ("Critic output integrity rejected", "critic returned invalid JSON across")}


class DiagnosisError(ValueError):
    """Fixed code; never content or a path."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DiagnosisError(code)


# ------------------------------------------------------------ Node readers

def run_review_readers(*, node: str, state_path: str, feedback_path: str | None, as_of: datetime) -> dict:
    """Invoke the existing Node readers with fixed bounded arguments, no shell."""
    _require(bool(NODE) and os.path.isabs(NODE) and os.path.realpath(NODE) == NODE
             and Path(NODE).name in ("node", "nodejs") and node == NODE, "review_readers_node_not_pinned")
    argv = [node, str(READER_SCRIPT), "--state", state_path]
    if feedback_path is not None:
        argv += ["--feedback", feedback_path]
    argv += ["--as-of", as_of.isoformat()]
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "NO_PROXY": "*", "no_proxy": "*",
           "HOME": "/nonexistent-private-diagnosis"}
    try:
        output = _bounded_reader_output(argv, env)
    except (OSError, subprocess.TimeoutExpired):
        raise DiagnosisError("review_readers_unavailable") from None
    try:
        value = strict_json_loads(output.strip(), allow_floats=True)
    except (ValueError, UnicodeError):
        raise DiagnosisError("review_readers_output_invalid") from None
    _require(type(value) is dict and value.get("schema") == "theheat.private-review-inputs/v1", "review_readers_schema")
    return value


def _bounded_reader_output(argv: list[str], env: dict[str, str]) -> bytes:
    """Stop before retaining more than the fixed stdout bound; discard private stderr."""
    with subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
                          cwd=str(READER_SCRIPT.parent.parent)) as process:
        assert process.stdout is not None
        output = bytearray()
        deadline = time.monotonic() + 120
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise subprocess.TimeoutExpired(argv, 120)
                    chunk = os.read(process.stdout.fileno(), min(65536, MAX_READER_OUTPUT + 1 - len(output)))
                    if not chunk:
                        break
                    output.extend(chunk)
                    _require(len(output) <= MAX_READER_OUTPUT, "review_readers_output_over_limit")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            _require(process.returncode == 0, "review_readers_refused_input")
            return bytes(output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


# ------------------------------------------------------- component checks

def _component(name: str, status: str, **extra: Any) -> dict:
    return {"component": name, "status": status, **extra}


def verify_components(*, archives: list[VerifiedArchive], reconciliation: Any, copy_private: Any,
                      copy_import: Any, readers: dict | None, state: Any, as_of: datetime,
                      feedback: Any = None) -> tuple[list[dict], dict]:
    """Verify each optional component and its exact lineage before any join."""
    manifests = {a.manifest_sha256 for a in archives if a.status != "invalid"}
    components = [_component("archive", a.status, scope_id=a.scope_id, manifest_sha256=a.manifest_sha256,
                             problems=list(a.problems)) for a in archives]
    usable: dict[str, Any] = {"reconciliation": None, "copy_private": None, "copy_import": None, "readers": None}
    if reconciliation is None:
        components.append(_component("reconciliation", "absent"))
    else:
        try:
            report = invoice_evidence.verify_report(reconciliation)
            named = {s["manifest_sha256"] for s in report["inputs"]["archives"] if s.get("used")}
            if not named <= manifests or datetime.fromisoformat(report["as_of"]) > as_of:
                components.append(_component("reconciliation", "lineage_mismatch",
                                             report_sha256=report["report_sha256"]))
            else:
                usable["reconciliation"] = report
                components.append(_component("reconciliation", "verified", report_sha256=report["report_sha256"],
                                             archives=len(named)))
        except invoice_evidence.BillingEvidenceInvalid as exc:
            components.append(_component("reconciliation", "invalid", reason=str(exc)))
        except (KeyError, TypeError, ValueError, OverflowError):
            components.append(_component("reconciliation", "invalid", reason="report_shape"))
    if copy_private is None:
        components.append(_component("copy_review", "absent"))
        if copy_import is not None:
            components.append(_component("copy_ratings", "invalid", reason="copy_private_required"))
    else:
        try:
            pack = private_copy_pack.verify_private_record(copy_private)
            named = {a["manifest_sha256"] for a in copy_private.get("archives", []) if a.get("status") != "invalid"}
            if (not named <= manifests or not _copy_lineage_matches(copy_private, archives)
                    or datetime.fromisoformat(copy_private["created_at"]) > as_of):
                components.append(_component("copy_review", "lineage_mismatch", pack_id=pack["pack_id"]))
            else:
                usable["copy_private"] = copy_private
                components.append(_component("copy_review", "verified", pack_id=pack["pack_id"],
                                             pack_sha256=pack["pack_sha256"]))
                if copy_import is None:
                    components.append(_component("copy_ratings", "absent"))
                else:
                    try:
                        imported = private_copy_pack.verify_import_report(copy_import, copy_private, as_of=as_of)
                        usable["copy_import"] = imported
                        components.append(_component("copy_ratings", "verified", pack_id=pack["pack_id"],
                                                     import_sha256=imported["report_sha256"]))
                    except private_copy_pack.CopyReviewError as exc:
                        components.append(_component("copy_ratings", "invalid", reason=str(exc)))
        except private_copy_pack.CopyReviewError as exc:
            components.append(_component("copy_review", "invalid", reason=str(exc)))
    if readers is None:
        components.append(_component("retained_state", "absent"))
        if feedback is not None:
            components.append(_component("feedback", "invalid", reason="retained_state_required"))
    else:
        semantic = readers["weekly"].get("input_semantic_sha256", {}).get("state")
        feedback_semantic = readers["weekly"].get("input_semantic_sha256", {}).get("feedback")
        expected_feedback = fingerprint(feedback["records"]) if type(feedback) is dict and "records" in feedback else None
        if (state is None or fingerprint(state) != semantic or feedback_semantic != expected_feedback
                or datetime.fromisoformat(readers["as_of"].replace("Z", "+00:00")) != as_of):
            components.append(_component("retained_state", "lineage_mismatch"))
        else:
            usable["readers"] = readers
            components.append(_component("retained_state", "verified", state_semantic_sha256=semantic,
                                         weekly_report_id=readers["weekly"]["report_id"],
                                         feedback="supplied" if readers["feedback_supplied"] else "absent"))
    return components, usable


def _copy_lineage_matches(private: dict, archives: list[VerifiedArchive]) -> bool:
    """Check private producer assertions against the actually supplied verified records."""
    try:
        return _copy_lineage_matches_checked(private, archives)
    except (KeyError, TypeError, ValueError):
        return False


def _copy_lineage_matches_checked(private: dict, archives: list[VerifiedArchive]) -> bool:
    by_scope = {archive.scope_id: archive for archive in archives if archive.status != "invalid"}
    if len(by_scope) != len([a for a in archives if a.status != "invalid"]):
        return False
    for named in private["archives"]:
        archive = by_scope.get(named["scope_id"])
        if archive is None or (archive.manifest_sha256, archive.status) != (named["manifest_sha256"], named["status"]):
            return False
    for pair in private["pairs_input"]:
        for candidate in pair["candidates"]:
            provenance = private["provenance"][candidate["candidate_id"]]
            archive = by_scope.get(provenance["scope_id"])
            if archive is None or archive.manifest_sha256 != provenance["manifest_sha256"]:
                return False
            manual = provenance["kind"] == "manual_edit"
            digest = provenance["edited_from"]["candidate_text_sha256"] if manual else candidate["text_sha256"]
            matches = [(generation, item) for generation in lineage(archive) for item in generation["candidates"]
                       if item["candidate_text_sha256"] == digest]
            if len(matches) != 1:
                return False
            generation, item = matches[0]
            if generation["bundle_sha256"] != provenance["bundle_sha256"]:
                return False
            if not manual and (item["attempt"] != provenance["attempt"] or generation["terminal"] != provenance["terminal"]
                               or {s: e["outcome"] for s, e in item["stages"].items()} != provenance["model_check_outcomes"]):
                return False
    return True


# --------------------------------------------------------------- diagnosis

def _reason_class(archive: VerifiedArchive, stage: str | None, artifact: str | None) -> str | None:
    if stage not in _SCHEMA_PHRASES or artifact is None:
        return None
    try:
        reason = archive.artifact(artifact).decode("utf-8")
    except Exception:
        return None
    return "invalid_model_output_schema" if any(p in reason for p in _SCHEMA_PHRASES[stage]) else None


def _attempt_index(reconciliation: dict | None) -> tuple[dict, dict]:
    usage: dict[tuple, dict] = {}
    billing: dict[tuple, str] = {}
    if reconciliation is None:
        return usage, billing
    for row in reconciliation["usage_attempts"]:
        usage[(row["scope_id"], row["call"], row["attempt"])] = row
    for match in reconciliation["reconciliation"]["matches"]:
        billing[(match["scope_id"], match["call"], match["attempt"])] = "matched"
    for conflict in reconciliation["reconciliation"]["conflicting_matches"]:
        for key in conflict.get("attempts", []):
            billing[tuple(key)] = "conflict"
    return usage, billing


def _call_view(archive: VerifiedArchive, call, usage: dict, billing: dict, has_billing: bool) -> tuple[dict, list[str]]:
    dispositions: list[str] = []
    attempts = []
    for attempt in call.attempts:
        key = (archive.scope_id, call.number, attempt.attempt)
        row = usage.get(key)
        bill = billing.get(key, "no_billing_item" if has_billing else "billing_absent")
        attempts.append({"attempt": attempt.attempt, "wire_request": attempt.request.availability,
                         "raw_response": attempt.response.availability, "http_status": attempt.status,
                         "usage_status": row["usage_status"] if row else "reconciliation_absent",
                         "billing": bill})
        if attempt.response.availability in ("not_observed", "read_failed"):
            dispositions.append(f"missing_response:call_{call.number}")
        if row and row["usage_status"] in ("absent", "invalid"):
            dispositions.append(f"usage_missing_or_invalid:call_{call.number}")
        if has_billing and bill != "matched":
            dispositions.append(f"billing_match_unresolved:call_{call.number}")
    result = call.result or {}
    if result.get("provider_outcome") == "unknown":
        dispositions.append(f"unknown_send_outcome:call_{call.number}")
    if call.result is None:
        dispositions.append(f"call_without_result:call_{call.number}")
    view = {"call": call.number, "stage": call.stage, "outcome": call.outcome,
            "logical_request": call.logical_request.availability, "physical_attempts": len(call.attempts),
            "provider_outcome": result.get("provider_outcome", "returned" if call.outcome == "returned" else None),
            "archival": result.get("archival"), "attempts": attempts}
    return view, dispositions


def _anchor(key: str) -> str:
    return "c-" + sha256_hex(key.encode("utf-8"))[:12]


def diagnose(*, archives: list[VerifiedArchive], components: list[dict], usable: dict, as_of: datetime,
             input_files: list[dict]) -> dict:
    _require(as_of.utcoffset() is not None, "as_of_not_aware")
    reconciliation, copy_private, copy_import, readers = (usable[k] for k in (
        "reconciliation", "copy_private", "copy_import", "readers"))
    usage, billing = _attempt_index(reconciliation)
    has_billing = bool(reconciliation and reconciliation["supplied_billing"]["documents"])
    copy_by_text: dict[tuple, dict] = {}
    if copy_private is not None:
        for pair in copy_private["pairs_input"]:
            for candidate in pair["candidates"]:
                record = copy_private["provenance"][candidate["candidate_id"]]
                if record["kind"] == "archive_candidate":
                    entry = copy_by_text.setdefault((record["scope_id"], candidate["text_sha256"]),
                                                    {"in_pack": True, "pair_kinds": []})
                    entry["pair_kinds"] = sorted({*entry["pair_kinds"], copy_private["pair_kinds"][pair["pair_id"]]})
    posts = (readers or {}).get("outcomes", {}).get("posts", []) if readers else []
    candidates: list[dict] = []
    generations: list[dict] = []
    for archive in archives:
        if archive.status == "invalid":
            continue
        for index, generation in enumerate(lineage(archive)):
            start = archive.inputs[index]["seq"]
            end = archive.inputs[index + 1]["seq"] if index + 1 < len(archive.inputs) else float("inf")
            generation_key = f"{archive.scope_id}:generation:{start}"
            local_calls = [call for call in archive.calls if start < call.intent_seq < end]
            local_candidates = [candidate for candidate in archive.candidates if start < candidate["seq"] < end]
            local_terminals = [record for record in archive.terminals if start < record["seq"] < end]
            terminal = generation["terminal"] if isinstance(generation["terminal"], dict) else None
            terminal_record = local_terminals[-1] if local_terminals else None
            writer_dispositions: list[str] = []
            writer_calls = []
            for call in local_calls:
                if call.stage == "writer":
                    view, found = _call_view(archive, call, usage, billing, has_billing)
                    writer_calls.append(view)
                    writer_dispositions += found
            kill_stage = terminal.get("kill_stage") if terminal else None
            schema = _reason_class(archive, kill_stage, terminal_record.get("kill_reason_artifact")
                                   if terminal_record else None)
            generation_row = {
                "scope_id": archive.scope_id, "archive_status": archive.status, "event_id": generation["event_id"],
                "generation_key": generation_key, "generation_seq": start,
                "bundle_sha256": generation["bundle_sha256"], "memory_sha256": generation["memory_sha256"],
                "terminal": terminal if terminal else "unavailable",
                "writer_calls": writer_calls, "candidate_count": len(generation["candidates"]),
                "dispositions": sorted(set(writer_dispositions + ([f"{schema}:{kill_stage}"] if schema else [])
                                           + ([] if terminal else ["no_terminal_recorded"])
                                           + ([f"archive_{archive.status}"] if archive.status != "complete" else [])))}
            generations.append(generation_row)
            for candidate_index, candidate in enumerate(local_candidates):
                digest, candidate_seq = candidate["candidate_text_sha256"], candidate["seq"]
                candidate_end = (local_candidates[candidate_index + 1]["seq"]
                                 if candidate_index + 1 < len(local_candidates) else end)
                key = f"{generation_key}:candidate:{candidate_seq}:attempt:{candidate['attempt']}:{digest}"
                calls, dispositions = [], []
                candidate_stages: dict[str, dict] = {}
                for call in local_calls:
                    if (candidate_seq < call.intent_seq < candidate_end
                            and call.binding.get("candidate_text_sha256") == digest
                            and call.binding.get("candidate_attempt") == candidate["attempt"]):
                        view, found = _call_view(archive, call, usage, billing, has_billing)
                        calls.append(view)
                        dispositions += found
                        candidate_stages.setdefault(call.stage, {"outcome": None, "calls": []})["calls"].append(
                            {"call": call.number})
                for outcome in archive.stage_outcomes:
                    binding = outcome.get("binding") or {}
                    if (candidate_seq < outcome["seq"] < candidate_end
                            and binding.get("candidate_text_sha256") == digest
                            and binding.get("candidate_attempt") == candidate["attempt"]):
                        candidate_stages.setdefault(outcome["stage"], {"outcome": None, "calls": []})["outcome"] = outcome["outcome"]
                for stage, entry in candidate_stages.items():
                    entry["disposition"] = ("provider_called" if entry["calls"] else
                                            "decided_without_provider_call" if entry["outcome"] else "no_decision_recorded")
                    if entry["disposition"] == "decided_without_provider_call":
                        dispositions.append(f"decided_without_provider_call:{stage}")
                matching_terminal_candidates = [c for c in local_candidates if terminal and
                                                c["candidate_text_sha256"] == terminal.get("draft_text_sha256")]
                ambiguous = bool(terminal and terminal.get("accepted") and len(matching_terminal_candidates) > 1
                                 and terminal.get("draft_text_sha256") == digest)
                accepted_here = bool(terminal and terminal.get("accepted") and terminal.get("draft_text_sha256") == digest
                                     and terminal.get("reviewed_bundle_sha256") == generation["bundle_sha256"]
                                     and len(matching_terminal_candidates) == 1)
                rejected = sorted(stage for stage, entry in candidate_stages.items() if entry["outcome"] == "kill")
                decision = ("accepted" if accepted_here else f"rejected_at:{rejected[-1]}" if rejected
                            else "superseded_or_undecided")
                if ambiguous:
                    dispositions.append("terminal_candidate_identity_ambiguous")
                if schema and kill_stage in rejected:
                    dispositions.append(f"{schema}:{kill_stage}")
                candidates.append({
                    "anchor": _anchor(key), "candidate_key": key, "scope_id": archive.scope_id,
                    "generation_seq": start, "candidate_seq": candidate_seq,
                    "signal_kind": archive.inputs[index].get("signal_kind"),
                    "archive_status": archive.status, "event_id": generation["event_id"],
                    "bundle_sha256": generation["bundle_sha256"], "memory_sha256": generation["memory_sha256"],
                    "candidate_text_sha256": digest, "attempt": candidate["attempt"], "decision": decision,
                    "stages": {s: {"outcome": e["outcome"], "disposition": e["disposition"],
                                   "calls": [c["call"] for c in e["calls"]]} for s, e in sorted(candidate_stages.items())},
                    "calls": calls, "copy_review": copy_by_text.get((archive.scope_id, digest), {"in_pack": False}),
                    "accepted_terminal": accepted_here,
                    "dispositions": sorted(set(dispositions + (["archive_incomplete"] if archive.status != "complete"
                                                               else [])))})
    joined_posts = _join_publications(candidates, posts)
    unjoined = [_post_row(post, joined_posts.get(post["tweet_id"])) for post in posts
                if joined_posts.get(post["tweet_id"]) != "joined"]
    report = {"schema": SCHEMA, "view_renderer": VIEW_RENDERER, "as_of": as_of.isoformat(), "components": components,
              "inputs": sorted(input_files, key=lambda f: (f["role"], f["sha256"])),
              "overview": _overview(archives, candidates, generations, reconciliation, copy_private, copy_import,
                                    readers, unjoined),
              "candidates": candidates, "generations": generations, "unjoined_posts": unjoined,
              "copy_review": _copy_summary(copy_private, copy_import),
              "decision": {"promotion": "HOLD", "weekly_review_decision": (readers or {}).get("weekly", {}).get(
                  "decision", {}).get("promotion") if readers else "absent",
                  "automatic_changes": False, "approvals": "none", "budget_released": False,
                  "provider_replay": False, "publication_authorized": False},
              "limits": ["Mechanical dispositions only; no root cause, weather diagnosis or quality grade.",
                         "Receipt joins require exact writer, source, unchanged saved revision and receipt identities; actor remains unknown.",
                         "Missing optional inputs are absent, never zero usage, cost, engagement or proof.",
                         "Billing is operator-supplied; ratings may be synthetic; neither certifies the other.",
                         "No action here generates, replays, approves, releases budget, posts or corrects."]}
    if any(archive.schema == SCHEMA_V2 and archive.status != "invalid" for archive in archives):
        # Route families exist only in explicit v2 archives; v1-only reports are unchanged.
        report["routes"] = _routes_section(archives)
    report["report_sha256"] = _identity(report)
    return report


def _route_dispositions(row: dict) -> list[str]:
    """Mechanical labels only: what the retained route evidence does and does not show."""
    out = ["billing_unknown"]
    if row["archival"] != "complete":
        out.append("archive_incomplete")
    if not row["physical_send_observed"]:
        out.append("no_physical_send")
    elif row["entity"] != "captured":
        out.append(f"entity_{row['entity']}")
    elif row["entity_complete"] is False:
        out.append("entity_partial")
    if row.get("evidence_gap"):
        out.append(f"evidence_gap:{row['evidence_gap']}")
    if row["family"] == "batch_submit":
        out.append("acknowledgment_not_completion_or_usage")
    elif row["family"] == "batch_metadata":
        out.append("status_read_not_generation")
        out.append(f"batch_identity_{row['batch_identity']}")
        if row["results_disposition"] == "unresolved":
            out.append("status_not_certified_for_requested_batch")
    elif row["family"] == "batch_results":
        results = row.get("results") or {}
        out.append(f"results_{results.get('status')}")
        if results.get("duplicate_custom_ids"):
            out.append("duplicate_custom_ids_visible")
        if results.get("unknown_custom_ids"):
            out.append("unknown_custom_ids_visible")
    if "predecessor" in row:
        out.append(f"predecessor_{row['predecessor']}")
    return sorted(set(out))


def _routes_section(archives: list[VerifiedArchive]) -> dict:
    # The same capture supplied twice is one scope; one identity with two contents is shown, never chosen.
    usage = archive_usage.archive_usage(archives)
    used = [archives[source["input"]] for source in usage["sources"] if source["used"]]
    conflicted = {(source["scope_id"], source["route"]) for conflict in usage.get("route_conflicts", [])
                  for source in conflict["sources"]}
    scopes = []
    for archive in used:
        if archive.schema != SCHEMA_V2:
            continue
        view = route_lineage(archive)
        families = sorted({row["family"] for row in view["routes"]})
        scopes.append({"scope_id": archive.scope_id, "archive_status": archive.status,
                       "families_observed": families,
                       "families_not_observed": sorted(set(ROUTES) - set(families)),
                       "reused_provider_batch_ids": view["reused_provider_batch_ids"],
                       "routes": [{"route": row["route"], "family": row["family"], "outcome": row["outcome"],
                                   "provider_batch_id": row.get("provider_batch_id"),
                                   "dispositions": sorted(_route_dispositions(row) + (
                                       ["result_conflict_with_other_retained_line"]
                                       if (archive.scope_id, row["route"]) in conflicted else []))}
                                  for row in view["routes"]]})
    return {"scopes": scopes, "supported_families": sorted(ROUTES),
            "identity_reconciliation": usage["identity_reconciliation"],
            "result_conflicts": usage.get("route_conflicts", []),
            "route_totals_status": usage.get("route_totals_status"),
            "route_totals_unknown_reasons": usage.get("route_totals_unknown_reasons", []),
            "limits": ["A batch acknowledgment is never completion, usage or billing evidence.",
                       "Batch status reads are not model generations; results usage counts once per custom ID.",
                       "Differing retained results for one custom ID are conflicts with every source; none is chosen.",
                       "A status body naming another batch, or none, is never attributed to the requested batch.",
                       "Links are observed_in_scope, durable_status_reference or unverified; nothing is fetched or repaired.",
                       "Route families outside the four supported ones are not captured by this archive."]}


def _join_publications(candidates: list[dict], posts: list[dict]) -> dict[str, str]:
    """Join only supported original writer -> unchanged saved revision -> receipt identities."""
    outcome: dict[str, str] = {}
    for candidate in candidates:
        candidate["publication"] = {"status": "not_published_in_supplied_state" if posts else "receipts_absent"}
    for post in posts:
        context = post.get("publication_context") or {}
        bundle = (context.get("source") or {}).get("bundle_sha256")
        digest = post.get("published_text_sha256")
        usable = post.get("revision_status") == "recorded" and context.get("status") == "recorded" and bundle
        same_text = [c for c in candidates if c["candidate_text_sha256"] == digest]
        exact = [c for c in same_text if usable and c["accepted_terminal"] and c["bundle_sha256"] == bundle
                 and _publication_lineage_matches(c, post)]
        if len(exact) == 1:
            publication = exact[0]["publication"]
            if publication["status"] != "joined":
                publication = exact[0]["publication"] = {"status": "joined", "posts": [],
                    "join": "writer_source_and_unchanged_revision_receipt_identity", "authorship": "unknown"}
            publication["posts"].append(_post_row(post, "joined"))
            exact[0]["dispositions"] = sorted(set(exact[0]["dispositions"]) | {"published_receipt_joined"})
            outcome[post["tweet_id"]] = "joined"
            continue
        outcome[post["tweet_id"]] = ("ambiguous_multiple_accepted_candidates" if len(exact) > 1
                                     else "publication_context_unavailable" if not usable
                                     else "candidate_revision_receipt_lineage_unavailable")
        for candidate in exact:
            candidate["publication"] = {"status": "ambiguous_join", "tweet_id": post["tweet_id"]}
        for candidate in same_text:
            if usable and candidate["bundle_sha256"] != bundle and candidate["publication"]["status"] != "joined":
                candidate["publication"] = {"status": "same_text_different_evidence", "tweet_id": post["tweet_id"],
                                            "join": "refused_identical_text_is_insufficient"}
                candidate["dispositions"] = sorted(set(candidate["dispositions"]) | {"evidence_changed_since_capture"})
    return outcome


def _publication_lineage_matches(candidate: dict, post: dict) -> bool:
    context = post.get("publication_context") or {}
    source, writer_context = context.get("source") or {}, post.get("writer_context") or {}
    writer, publication = writer_context.get("writer") or {}, writer_context.get("publication") or {}
    original, published = writer.get("original_identity"), publication.get("identity")
    return bool(writer_context.get("status") == "recorded" and writer_context.get("source_relation") == "matches"
                and writer_context.get("text_comparison") == "matches"
                and writer_context.get("retained_different_text") is False
                and writer_context.get("history_unavailable") is False
                and post.get("authorship") != "manual_or_edited"
                and original is not None and original == published
                and original.get("text_sha256") == candidate["candidate_text_sha256"]
                and writer.get("text_sha256") == candidate["candidate_text_sha256"]
                and source.get("event_id") == writer.get("event_id") == publication.get("event_id") == candidate["event_id"]
                and source.get("signal_kind") == candidate["signal_kind"]
                and writer.get("bundle_sha256") == publication.get("source_bundle_sha256") == candidate["bundle_sha256"])


def _post_row(post: dict, reason: str | None) -> dict:
    source = (post.get("publication_context") or {}).get("source") or {}
    return {"tweet_id": post["tweet_id"], "revision_status": post["revision_status"],
            "published_text_sha256": post["published_text_sha256"], "bundle_sha256": source.get("bundle_sha256"),
            "publication_context": (post.get("publication_context") or {}).get("status"),
            "observation_count": len(post["observations"]), "observations": post["observations"],
            "history_status": post["history_status"], "writer_context": post.get("writer_context"),
            "authorship": post.get("authorship"), "qualified_weekly_receipt": post.get("qualified_weekly_receipt", False),
            "join": reason or "no_exact_archived_candidate_for_text_and_bundle"}


def _copy_summary(copy_private: dict | None, copy_import: dict | None) -> dict:
    if copy_private is None:
        return {"status": "absent"}
    summary: dict[str, Any] = {"status": "verified", "pack_id": copy_private["pack_id"],
                               "pairs": len(copy_private["pairs_input"]), "held_pairs": len(copy_private["held"]),
                               "pair_kinds": sorted(copy_private["pair_kinds"].values())}
    if copy_import is None:
        summary["ratings"] = "absent"
        return summary
    summary["ratings"] = {
        "real_human_ratings_added": copy_import["real_human_ratings_added"],
        "human_asserted_preferences_by_display_side":
            copy_import["human_asserted_summary"]["eligible_preferences_by_display_side"],
        "synthetic_fixture_preferences_by_display_side":
            copy_import["synthetic_fixture_summary"]["eligible_preferences_by_display_side"],
        "conflicts": len(copy_import["conflicts"]), "identical_retries": copy_import["identical_retries_collapsed"],
        "refused": sum(1 for b in copy_import["ballots"] if b["outcome"] != "ballot_read"),
        "interpretation": copy_import["interpretation"]}
    return summary


def _overview(archives, candidates, generations, reconciliation, copy_private, copy_import, readers, unjoined) -> dict:
    statuses = [a.status for a in archives]
    spend: dict[str, Any] = {"status": "absent"}
    if reconciliation is not None:
        rec = reconciliation["reconciliation"]
        spend = {"status": "verified", **reconciliation["observed"]["denominators"],
                 "billing_matches": len(rec["matches"]), "unmatched_billing_items": len(rec["unmatched_billing_items"]),
                 "conflicting_matches": len(rec["conflicting_matches"]),
                 "quarantined_billing": len(reconciliation["supplied_billing"]["quarantined"]),
                 "scenario_token_component_usd": (reconciliation["priced_scenario"] or {}).get("token_component_usd"),
                 "billed_totals": reconciliation["supplied_billing"]["billed_totals_by_scope"],
                 "actual_cost_known": False}
    weekly = (readers or {}).get("weekly") if readers else None
    return {
        "source": {"archives": len(archives), "archive_statuses": {s: statuses.count(s) for s in sorted(set(statuses))},
                   "generations": len(generations), "distinct_bundles": len({g["bundle_sha256"] for g in generations})},
        "checks": {"candidates": len(candidates),
                   "accepted": sum(1 for c in candidates if c["decision"] == "accepted"),
                   "rejected": sum(1 for c in candidates if c["decision"].startswith("rejected_at:")),
                   "generations_without_candidate": sum(1 for g in generations if not g["candidate_count"]),
                   "decided_without_provider_call": sum(1 for c in candidates for d in c["dispositions"]
                                                        if d.startswith("decided_without_provider_call"))},
        "spend": spend,
        "preference": _copy_summary(copy_private, copy_import),
        "publication": ({"status": "verified", "weekly_delivery_count": weekly["delivery"]["count"],
                         "manual_or_edited": weekly["copy"]["manual_or_edited"],
                         "outcome_inventory_status": readers["outcomes"]["status"],
                         "outcome_inventory_rows": len(readers["outcomes"]["posts"]),
                         "posts_with_receipts": sum(1 for post in readers["outcomes"]["posts"]
                                                    if post["revision_status"] == "recorded"
                                                    and post["publication_context"]["status"] == "recorded"),
                         "joined_to_archived_candidate": sum(len(c["publication"]["posts"]) for c in candidates
                                                             if c["publication"]["status"] == "joined"),
                         "unjoined_posts": len(unjoined), "engagement_lift": None,
                         "editorial_feedback": weekly["editorial_feedback"], "exclusions": weekly["exclusions"],
                         "weekly_cost_context": weekly["cost_context"],
                         "feedback": "supplied" if readers and readers["feedback_supplied"] else "absent"}
                        if weekly else {"status": "absent"})}


def _identity(report: dict) -> str:
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    return sha256_hex(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8"))


def report_json(report: dict) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8")


# ----------------------------------------------------------------- views

def _md(value: Any) -> str:
    text = "—" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _view_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) if isinstance(value, (dict, list)) else str(value)


def render_markdown(report: dict) -> str:
    o = report["overview"]
    lines = [f"# Private diagnosis ({report['report_sha256'][:12]})", "",
             f"As of `{report['as_of']}`. Promotion: **HOLD**. No action here approves, replays, releases "
             "budget, posts or corrects.", "", "## Components", "", "| component | status | detail |", "|---|---|---|"]
    for component in report["components"]:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(component.items()) if k not in ("component", "status")
                           and not isinstance(v, list))
        lines.append(f"| {component['component']} | {component['status']} | {_md(detail or '—')} |")
    lines += ["", "## Overview (separate denominators)", ""]
    for section in ("source", "checks", "spend", "preference", "publication"):
        values = o[section]
        flat = ", ".join(f"{k}={_view_value(v)}" for k, v in sorted(values.items()))
        lines.append(f"- **{section}**: {_md(flat)}")
    lines += ["", "## Candidates", "", "| candidate | event | decision | dispositions | publication |",
              "|---|---|---|---|---|"]
    for c in report["candidates"]:
        lines.append(f"| `{c['anchor']}` | {_md(c['event_id'])} | {c['decision']} | "
                     f"{_md(', '.join(c['dispositions']) or 'none')} | {c['publication']['status']} |")
        if c["publication"]["status"] == "joined":
            lines.append(f"\nPublication evidence for `{c['anchor']}`: {_md(_view_value(c['publication']))}\n")
    lines += ["", "## Generations", "", "| scope | event | terminal | candidates | dispositions |", "|---|---|---|---|---|"]
    for g in report["generations"]:
        terminal = g["terminal"] if isinstance(g["terminal"], str) else (
            "accepted" if g["terminal"].get("accepted") else f"kill:{g['terminal'].get('kill_stage')}")
        lines.append(f"| {g['scope_id']} | {_md(g['event_id'])} | {terminal} | {g['candidate_count']} | "
                     f"{_md(', '.join(g['dispositions']) or 'none')} |")
    if report["unjoined_posts"]:
        lines += ["", "## Posts not joined to an archived candidate", "", "| tweet | revision | context | reason |",
                  "|---|---|---|---|"]
        lines += [f"| {p['tweet_id']} | {p['revision_status']} | {p['publication_context']} | {p['join']} |"
                  for p in report["unjoined_posts"]]
        lines += [f"\nOutcome evidence {p['tweet_id']}: {_md(_view_value(p))}" for p in report["unjoined_posts"]]
    lines += ["", "## Limits", ""] + [f"- {item}" for item in report["limits"]]
    return "\n".join(lines) + "\n"


def render_html(report: dict) -> str:
    """Static local view: no scripts, no external resources, every value escaped."""
    e = html.escape
    o = report["overview"]
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; "
             "img-src 'none'; form-action 'none'; base-uri 'none'\">",
             f"<title>Private diagnosis {e(report['report_sha256'][:12])}</title><style>",
             "body{font:16px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#fef9ef;color:#1a1a1a}"
             "p,li{overflow-wrap:anywhere}code{word-break:break-all}",
             "main{max-width:1040px;margin:0 auto;padding:16px}h1{font-size:28px}h2{font-size:22px;margin-top:32px}",
             "table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d9d2c3;padding:6px;"
             "text-align:left;vertical-align:top;overflow-wrap:break-word}code{font-family:ui-monospace,Menlo,monospace}",
             ".tag{display:inline-block;border:1px solid #6e5ebe;border-radius:12px;padding:0 8px;margin:2px;font-size:13px}",
             ".hold{border:2px solid #1a1a1a;padding:8px 12px;border-radius:8px}"
             "@media(max-width:700px){table{display:block;overflow-x:auto}th,td{white-space:nowrap}}"
             "</style></head><body><main>",
             f"<h1>Private diagnosis</h1><p><code>{e(report['report_sha256'])}</code> as of {e(report['as_of'])}</p>",
             "<p class='hold'><strong>Promotion: HOLD.</strong> This report approves nothing, releases no budget, "
             "replays no provider, posts nothing and corrects nothing.</p>",
             "<nav aria-label='Sections'><a href='#overview'>Overview</a> · <a href='#candidates'>Candidates</a> · "
             "<a href='#generations'>Generations</a> · <a href='#posts'>Unjoined posts</a> · "
             "<a href='#components'>Components</a></nav>", "<h2 id='overview'>Overview</h2>"]
    for section, title in (("source", "Source"), ("checks", "Checks"), ("spend", "Spend"),
                           ("preference", "Preference"), ("publication", "Publication")):
        rows = "".join(f"<tr><th scope='row'>{e(k)}</th><td>{e(_view_value(v))}</td></tr>"
                       for k, v in sorted(o[section].items()))
        parts.append(f"<h3>{title}</h3><table>{rows}</table>")
    parts.append("<h2 id='candidates'>Candidates</h2>")
    for c in report["candidates"]:
        calls = "".join(f"<tr><td>{x['call']}</td><td>{e(x['stage'])}</td><td>{e(x['outcome'])}</td>"
                        f"<td>{e(str(x['provider_outcome']))}</td><td>{e(x['logical_request'])}</td>"
                        f"<td>{e(', '.join(a['raw_response'] + '/' + a['usage_status'] + '/' + a['billing'] for a in x['attempts']) or 'no send')}</td></tr>"
                        for x in c["calls"])
        tags = "".join(f"<span class='tag'>{e(d)}</span>" for d in c["dispositions"]) or "none"
        parts.append(
            f"<section id='{e(c['anchor'])}' aria-labelledby='{e(c['anchor'])}-t'><h3 id='{e(c['anchor'])}-t'>"
            f"{e(c['decision'])} · <code>{e(c['anchor'])}</code></h3>"
            f"<p>Event {e(str(c['event_id']))}; archive <code>{e(c['scope_id'])}</code> ({e(c['archive_status'])}); "
            f"bundle <code>{e(c['bundle_sha256'])}</code>; candidate text <code>{e(c['candidate_text_sha256'])}</code>.</p>"
            f"<p>Dispositions: {tags}</p><p>Publication: {e(c['publication']['status'])}; copy review: "
            f"{e('in pack (' + ', '.join(c['copy_review']['pair_kinds']) + ')' if c['copy_review'].get('in_pack') else 'not in pack')}</p>"
            f"<p>Publication evidence: {e(_view_value(c['publication']))}</p>"
            "<table><thead><tr><th>call</th><th>stage</th><th>outcome</th><th>provider outcome</th><th>logical request</th>"
            f"<th>response / usage / billing</th></tr></thead><tbody>{calls}</tbody></table></section>")
    parts.append("<h2 id='generations'>Generations</h2><table><thead><tr><th>archive</th><th>event</th><th>terminal</th>"
                 "<th>candidates</th><th>dispositions</th></tr></thead><tbody>")
    for g in report["generations"]:
        terminal = g["terminal"] if isinstance(g["terminal"], str) else (
            "accepted" if g["terminal"].get("accepted") else f"kill: {g['terminal'].get('kill_stage')}")
        parts.append(f"<tr><td><code>{e(g['scope_id'])}</code></td><td>{e(str(g['event_id']))}</td><td>{e(terminal)}</td>"
                     f"<td>{g['candidate_count']}</td><td>{e(', '.join(g['dispositions']) or 'none')}</td></tr>")
    parts.append("</tbody></table><h2 id='posts'>Posts not joined to an archived candidate</h2>")
    if report["unjoined_posts"]:
        parts.append("<table><thead><tr><th>tweet</th><th>revision</th><th>context</th><th>observations</th><th>reason</th>"
                     "</tr></thead><tbody>" + "".join(
                         f"<tr><td>{e(p['tweet_id'])}</td><td>{e(p['revision_status'])}</td><td>"
                         f"{e(str(p['publication_context']))}</td><td>{p['observation_count']}</td><td>{e(p['join'])}</td></tr>"
                         for p in report["unjoined_posts"]) + "</tbody></table>")
        parts += [f"<p>Outcome evidence {e(p['tweet_id'])}: {e(_view_value(p))}</p>" for p in report["unjoined_posts"]]
    else:
        parts.append("<p>None in the supplied state (or no state supplied).</p>")
    parts.append("<h2 id='components'>Components</h2><table><thead><tr><th>component</th><th>status</th></tr></thead><tbody>")
    parts += [f"<tr><td>{e(c['component'])}</td><td>{e(c['status'])}</td></tr>" for c in report["components"]]
    parts.append("</tbody></table><h2>Limits</h2><ul>" + "".join(f"<li>{e(item)}</li>" for item in report["limits"])
                 + "</ul></main></body></html>\n")
    return "".join(parts)


# ----------------------------------------------------- durable output

def write_report(output_dir: str | os.PathLike, report: dict) -> dict:
    """Write components, then a completion marker last. Exact retries are idempotent."""
    directory = require_private_directory(output_dir, create=False)
    payloads = {"diagnosis.json": report_json(report), "diagnosis.md": render_markdown(report).encode("utf-8"),
                "diagnosis.html": render_html(report).encode("utf-8")}
    _require(all(len(data) <= MAX_REPORT_COMPONENT_BYTES for data in payloads.values()), "diagnosis_output_over_limit")
    written = {name: write_private_file_exclusive(directory, name, data) for name, data in payloads.items()}
    marker = {"schema": SCHEMA, "report_sha256": report["report_sha256"],
              "components": {name: sha256_hex(data) for name, data in payloads.items()}}
    written[MARKER] = write_private_file_exclusive(directory, MARKER, report_json(marker))
    return {name: "new" if value else "identical_existing" for name, value in written.items()}


def verify_output(output_dir: str | os.PathLike) -> dict:
    """A diagnosis is complete only with a marker whose hashes match re-rendered bytes."""
    directory = require_private_directory(output_dir, create=False)
    try:
        marker = strict_json_loads(read_private_file(directory / MARKER, 1 << 20))
    except FileNotFoundError:
        return {"status": "incomplete", "reason": "completion_marker_missing"}
    except (OSError, ValueError, UnicodeError, RequestArchiveRefused):
        return {"status": "invalid", "reason": "completion_marker_unreadable"}
    try:
        payloads = {name: read_private_file(directory / name, MAX_REPORT_COMPONENT_BYTES) for name in COMPONENTS}
    except FileNotFoundError:
        return {"status": "invalid", "reason": "component_missing"}
    except (OSError, RequestArchiveRefused):
        return {"status": "invalid", "reason": "component_unreadable"}
    if type(marker) is not dict or marker.get("components") != {n: sha256_hex(d) for n, d in payloads.items()}:
        return {"status": "invalid", "reason": "component_hash_mismatch"}
    try:
        report = strict_json_loads(payloads["diagnosis.json"], allow_floats=True)
    except (ValueError, UnicodeError):
        return {"status": "invalid", "reason": "report_unparseable"}
    if (type(report) is not dict or report.get("schema") != SCHEMA or report.get("report_sha256") != _identity(report)
            or report["report_sha256"] != marker.get("report_sha256")):
        return {"status": "invalid", "reason": "report_identity_mismatch"}
    if report.get("view_renderer") != VIEW_RENDERER:
        return {"status": "unverifiable_views", "reason": "view_renderer_version_differs"}
    if (render_markdown(report).encode("utf-8") != payloads["diagnosis.md"]
            or render_html(report).encode("utf-8") != payloads["diagnosis.html"]
            or report_json(report) != payloads["diagnosis.json"]):
        return {"status": "invalid", "reason": "view_not_derived_from_report"}
    return {"status": "complete", "report_sha256": report["report_sha256"],
            "candidates": len(report["candidates"]), "promotion": report["decision"]["promotion"]}
