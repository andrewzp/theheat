"""Offline, bounded adversarial observations anchored to the P00a freeze.

This is neither a historical runtime reproduction nor an editorial quality test.
Only the explicit targeted code satisfies a rejection expectation. Reaching the
checker model boundary means further verification is required, never a pass.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import date
import io
from pathlib import Path
import re
import socket
import subprocess
import tempfile
from unittest.mock import patch

from src.evaluation.incumbent import _encode, _hash, _json, verify


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "tests/fixtures/historical_scientific_cases.json"
PROBES = ROOT / "tests/fixtures/historical_scientific_probes.json"
LIMITS = [
    "Targeted retained failures; not representative tweets or worldwide event coverage.",
    "No provider calls, incumbent generation, blind editorial judgments, reach or cost-lift measurement.",
    "Exact-text probes use synthetic structural evidence, not recovered complete historical input packets.",
    "Pipeline probes inject writer output and disable optional LLM safety locally; neither is evaluated.",
    "A control reaching the checker boundary still requires verification; it is not publishable gold.",
    "Local lexical checks are bounded and do not establish complete semantic or scientific correctness.",
]
RUNTIME_FILES = (
    "src/evaluation/historical.py", "src/two_bot/pipeline.py", "src/two_bot/fact_check.py",
    "src/two_bot/scientific_claims.py", "src/two_bot/strict_contract.py",
    "src/two_bot/evidence_contract.py", "src/two_bot/types.py", "src/voice/safety.py",
    "src/data/temperature_evidence.py", "src/data/ghcn.py", "src/data/ghcn_format.py",
    "src/data/temperature_history.py", "src/editorial/revisions.py",
)


class OfflineViolation(BaseException):
    """Bypass production catch-and-continue handlers on unexpected I/O."""


class VerificationRequired(BaseException):
    """Expected checker boundary reached; no provider function executed."""


@contextmanager
def offline_boundaries():
    """Fail before provider/transport/process I/O, including swallowed errors.

    This runner is single-process, single-threaded; patches are restored on exit.
    The counters also detect a caller that catches BaseException internally.
    """
    from src.two_bot import critic, fact_check, writer
    calls: Counter = Counter()

    def forbidden(*_args, **_kwargs):
        calls["unexpected_boundary_attempts"] += 1
        raise OfflineViolation("Unexpected provider/network/process boundary; offline evaluation aborted")

    def needs_verification(*_args, **_kwargs):
        calls["checker_boundary_reached"] += 1
        raise VerificationRequired()

    with ExitStack() as stack:
        for target in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"):
            if hasattr(socket.socket, target):
                stack.enter_context(patch.object(socket.socket, target, forbidden))
        for target in ("create_connection", "getaddrinfo"):
            stack.enter_context(patch.object(socket, target, forbidden))
        stack.enter_context(patch.object(subprocess, "Popen", forbidden))
        for module, names in ((writer, ("write_tweet", "_call_anthropic", "_call_google")),
                              (critic, ("critic_review", "critic_select_slate"))):
            for name in names:
                stack.enter_context(patch.object(module, name, forbidden))
        stack.enter_context(patch.object(fact_check, "_call_gemini", needs_verification))
        yield calls
        if calls["unexpected_boundary_attempts"]:
            raise OfflineViolation("An unexpected offline boundary attempt was caught by the caller")


def load_catalog(catalog=CATALOG, probes=PROBES):
    labels = _json(Path(catalog).read_bytes())
    executions = _json(Path(probes).read_bytes())
    rows = labels["cases"]
    specs = executions["cases"]
    ids = [row["case_id"] for row in rows]
    if len(set(ids)) != len(ids) or {row["case_id"] for row in specs} != set(ids) or len(specs) != len(ids):
        raise ValueError("Each audited case must have exactly one executable specification")
    if any(not row.get("evidence_limit") or not row.get("expected_rejection") for row in rows):
        raise ValueError("Adjudication and evidence limits are required")
    probe_ids = []
    for spec in specs:
        if not spec.get("capability_limit"):
            raise ValueError("An execution capability limit is required")
        for variant in spec["variants"]:
            probe_ids.append(variant["probe_id"])
            outcome = variant["expected_outcome"]
            if outcome not in {"targeted_rejection", "verification_required"}:
                raise ValueError("Unsupported expectation")
            if bool(variant["expected_codes"]) != (outcome == "targeted_rejection"):
                raise ValueError("A targeted rejection must name its expected codes")
    if len(set(probe_ids)) != len(probe_ids):
        raise ValueError("Duplicate probe identity")
    return rows, {row["case_id"]: row for row in specs}


def structural_bundle(spec):
    """Deliberately engineered minimum evidence, never historical provenance."""
    from src.two_bot.types import StoryBundle
    signal = spec["signal_kind"]
    unit = "MW" if signal == "fire" else "mm" if signal.startswith("precipitation") else "C"
    return StoryBundle(
        signal_kind=signal, event_id=f"synthetic_{spec['case_id']}",
        where="Synthetic probe location", when="2026-07-01",
        headline_metric={"label": "synthetic_measurement", "value": 40, "unit": unit},
        current_facts=[{"label": "source", "value": "synthetic-structural-probe"}],
        raw_signal_dump={"source_product": "synthetic-structural-probe",
                         "evidence": deepcopy(spec["structural_evidence"])},
    )


def failure_codes(failures):
    """Only fixed identifiers leave the runner; never raw failure text."""
    codes = set()
    for reason in failures:
        if "temperature evidence: forecast cannot support an observed temperature/record claim" in reason:
            codes.add("temperature_forecast_as_observation")
        elif reason.startswith("temperature evidence:"):
            codes.add("temperature_scope_unqualified")
        else:
            prefix = reason.split(":", 1)[0]
            if re.fullmatch(r"[a-z][a-z_]+", prefix):
                codes.add(prefix)
            else:
                codes.add("other_local_rejection")
    return sorted(codes)


def run_probe(tweet, spec, *, pipeline_mode=False):
    """Exercise production gates, intercepting rather than answering model calls."""
    from src.two_bot import fact_check, pipeline
    from src.two_bot.types import WriterResult
    from src.voice import safety
    bundle = structural_bundle(spec)
    telemetry: dict = {}
    codes = []
    outcome = "local_rejection"
    # Production diagnostics can contain private text; neither stream escapes.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), offline_boundaries() as calls:
        try:
            if pipeline_mode:
                injected = WriterResult(tweet, None, "offline_probe", None, None, "Injected offline text.")
                with patch.object(pipeline, "_writer_samples", return_value=1), \
                     patch.object(pipeline.writer, "write_tweet", return_value=injected), \
                     patch.object(safety, "GEMINI_API_KEY", ""):
                    result = pipeline.generate_draft(bundle, {}, result_out=telemetry)
                if result is not None:
                    raise OfflineViolation("A pipeline probe unexpectedly became an accepted draft")
                codes = failure_codes([telemetry.get("kill_reason", "")])
                # Multiple factual codes are joined in pipeline telemetry.
                if telemetry.get("kill_stage") == "fact_check":
                    codes = failure_codes(re.split(r"; (?=[a-z_]+:|temperature evidence:)", telemetry["kill_reason"]))
            else:
                checked = fact_check.fact_check(tweet, [], bundle, {})
                if checked.passed:
                    raise OfflineViolation("A local checker probe unexpectedly passed")
                codes = failure_codes(checked.failures)
        except VerificationRequired:
            outcome = "verification_required"
    return {"outcome": outcome, "observed_codes": codes, "provider_calls": 0,
            "checker_boundary_reached": calls["checker_boundary_reached"],
            "unexpected_boundary_attempts": calls["unexpected_boundary_attempts"],
            "pipeline_kill_stage": telemetry.get("kill_stage") if pipeline_mode else None}


def observe_packet(packet):
    """Never fill missing source fields to turn a retained summary into evidence."""
    from src.two_bot import pipeline
    from src.two_bot.types import StoryBundle
    if not isinstance(packet, dict):
        return {"outcome": "missing_retained_packet", "provider_calls": 0}
    required = {"signal_kind", "where", "when", "event_id", "headline_metric", "current_facts"}
    if required - set(packet):
        return {"outcome": "incomplete_legacy_packet", "missing_fields": sorted(required - set(packet)), "provider_calls": 0}
    try:
        bundle = StoryBundle(**deepcopy(packet))
    except (TypeError, ValueError):
        return {"outcome": "incompatible_legacy_packet", "provider_calls": 0}
    telemetry: dict = {}
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), offline_boundaries():
        # A prompt-ready packet reaching a writer is an unsupported offline
        # path and must fail loudly, rather than be mistaken for an abstention.
        result = pipeline.generate_draft(bundle, {}, result_out=telemetry)
    if result is not None or telemetry.get("kill_stage") != "evidence_contract":
        raise OfflineViolation("Retained packet did not abstain at the evidence boundary")
    issues = telemetry.get("evidence_readiness", {}).get("issues", [])
    return {"outcome": "legacy_packet_evidence_abstention", "provider_calls": 0,
            "observed_codes": sorted({row["code"] for row in issues if row.get("severity") == "error"})}


def expected_matches(observation, variant):
    if variant["expected_outcome"] == "verification_required":
        return observation["outcome"] == "verification_required"
    return (observation["outcome"] == "local_rejection"
            and set(variant["expected_codes"]).issubset(observation["observed_codes"]))


def source_observations(package, state):
    """Use the actual frozen NOAA bytes with current P06 functions, offline."""
    from src.data import ghcn
    from src.data.ghcn_format import DailyObs
    from src.data.temperature_history import retained_claims, tracked_points
    path = package / "evidence/beaver-ghcn-as-retrieved-2026-09-08.dly"
    if not path.is_file():
        return {"outcome": "needs_source", "expected_codes": ["current_qc_exclusion", "affected_claim_retained"]}
    payload = path.read_bytes()
    local_state = deepcopy(state)
    before = deepcopy(local_state.get("drafts"))
    with offline_boundaries():
        snapshot = ghcn._archive_snapshot("USS0011K13S", payload, "2026-09-08")
        thresholds, accepted = ghcn._thresholds_from_verified_archive(
            "USS0011K13S", [DailyObs("USS0011K13S", date(2026, 6, 25), "TMAX", 39.9)], snapshot)
        claims = retained_claims(local_state)
        ghcn._retain_snapshot_revisions(local_state, "USS0011K13S", snapshot, claims, tracked_points(local_state))
    rows = list(local_state.get("temperature_history", {}).values())
    point = snapshot["records"].get((date(2026, 6, 25), "TMAX"))
    prior = thresholds.provenance.get("variables", {}).get("temperature_2m_max", {})
    findings = [row for row in rows if row.get("kind") == "affected_claim"
                and row.get("claim", {}).get("valid_date") == "2026-06-25"]
    codes = []
    if point and point.value_c == 39.9 and point.qflag == "S" and not accepted:
        codes.append("current_qc_exclusion")
    if any(row.get("reason") == "current_source_qc_or_value_revision" for row in findings):
        codes.append("affected_claim_retained")
    if before == local_state.get("drafts"):
        codes.append("retained_drafts_unchanged")
    if all(row.get("details", {}).get("publication_time_flag_timing") == "unknown"
           for row in findings if row.get("reason") == "current_source_qc_or_value_revision") and findings:
        codes.append("publication_time_qc_unknown")
    if thresholds.all_time_max_c == 36.0 and prior.get("previous_date") == "2026-06-16":
        codes.append("current_accepted_comparator_progression")
    expected = ["current_qc_exclusion", "affected_claim_retained", "retained_drafts_unchanged", "publication_time_qc_unknown",
                "current_accepted_comparator_progression"]
    return {"outcome": "source_byte_observation", "source_sha256": _hash(payload),
            "expected_codes": expected, "observed_codes": codes,
            "expectation_met": set(expected).issubset(codes), "provider_calls": 0,
            "cutoff": thresholds.provenance.get("cutoff"),
            "source_coverage_complete": prior.get("source_coverage_complete"),
            "current_accepted_previous_value_c": thresholds.all_time_max_c,
            "current_accepted_previous_date": prior.get("previous_date"),
            "progression_limit": "Frozen retrieval includes a June16 36.0C accepted cell; June12 need not be the immediately previous maximum. These are current accepted samples, not publication-time certification.",
            "retrieval_time_limit": "Only the audit retrieval date is known; an exact acquisition time is not reconstructed."}


def evaluate(package: Path, manifest_sha256: str):
    verification = verify(package, manifest_sha256)
    labels, specs = load_catalog()
    frozen_labels = _json((package / "scientific-cases.json").read_bytes())
    if frozen_labels["cases"] != labels:
        raise ValueError("Current adjudication catalog differs from the verified frozen catalog")
    corpus = _json((package / "corpus.json").read_bytes())
    state = _json((package / "source-state.json").read_bytes())
    originals = {row["audit_id"]: row for row in corpus}
    report: dict = {"schema_version": 1, "baseline": verification, "limits": LIMITS,
              "catalog_sha256": _hash(CATALOG.read_bytes()), "probe_spec_sha256": _hash(PROBES.read_bytes()),
              "runtime_source_sha256": {path: _hash((ROOT / path).read_bytes()) for path in RUNTIME_FILES},
              "cases": [], "provider_calls": 0}
    private: dict = {"schema_version": 1, "baseline_manifest_sha256": manifest_sha256, "texts": []}
    for label in labels:
        spec = specs[label["case_id"]]
        result = {**label, "capability_limit": spec["capability_limit"],
                  "required_scientific_outcome": spec["required_scientific_outcome"],
                  "retained": [], "structural_probes": []}
        # Public labels contain adjudication summaries, never original full text.
        for audit_id in label["audit_ids"]:
            row = originals[audit_id]
            drafts = [d for d in state["drafts"] if d.get("event_id") == row["event_id"] and d.get("text") == row["text"]]
            if len(drafts) > 1:
                raise ValueError(f"Ambiguous retained draft join: {audit_id}")
            packet = drafts[0].get("review_context", {}).get("two_bot", {}).get("bundle") if drafts else None
            identity = {"audit_id": audit_id, "text_sha256": _hash(row["text"].encode()),
                        "publication_evidence": row["publication_evidence"]}
            private["texts"].append({**identity, "case_id": label["case_id"], "original": row,
                                     "retained_draft": drafts[0] if drafts else None})
            retained = {**identity, "packet": observe_packet(packet)}
            if spec["exact_text_expected_codes"]:
                observation = run_probe(row["text"], spec)
                retained["exact_text_synthetic_evidence_probe"] = {
                    **observation, "expected_codes": spec["exact_text_expected_codes"],
                    "expectation_met": set(spec["exact_text_expected_codes"]).issubset(observation["observed_codes"])}
            else:
                retained["exact_text_synthetic_evidence_probe"] = {"outcome": "not_adjudicated_by_text_guard"}
            result["retained"].append(retained)
        for variant in spec["variants"]:
            observation = run_probe(variant["tweet"], spec, pipeline_mode=True)
            result["structural_probes"].append({"probe_id": variant["probe_id"],
                "text_sha256": _hash(variant["tweet"].encode()), "expected_outcome": variant["expected_outcome"],
                "expected_codes": variant["expected_codes"], **observation,
                "required_capability": variant.get("required_capability", "bounded_text_guard_only"),
                "expectation_met": expected_matches(observation, variant)})
        if label["case_id"] == "record_progression_and_later_quality_revision":
            result["source_observation"] = source_observations(package, state)
        report["cases"].append(result)
    return report, private


def unexpected_observations(report):
    """Return identities only, without converting recorded coverage gaps to wins."""
    unexpected = []
    for case in report["cases"]:
        for probe in case["structural_probes"]:
            if not probe["expectation_met"]:
                unexpected.append(f"{case['case_id']}:{probe['probe_id']}")
        for row in case["retained"]:
            probe = row["exact_text_synthetic_evidence_probe"]
            if probe.get("expectation_met") is False:
                unexpected.append(f"{case['case_id']}:{row['audit_id']}")
        if case.get("source_observation", {}).get("expectation_met") is False:
            unexpected.append(f"{case['case_id']}:source_bytes")
    return unexpected


def write_private_results(output: Path, report, private, *, repository=ROOT):
    """Write a new ignored sibling directory, never the original frozen package."""
    original_output = Path(output).absolute()
    if any(path.is_symlink() for path in (original_output, *original_output.parents)):
        raise ValueError("Output cannot traverse symlinks")
    output = original_output.resolve()
    private_root = Path(repository).resolve() / ".gstack" / "benchmarks"
    if output.parent != private_root or output.resolve().parent != private_root.resolve():
        raise ValueError("Output must be a direct child of this repository's ignored .gstack/benchmarks")
    if any(path.is_symlink() for path in (output, *output.parents)) or output.exists():
        raise ValueError("Output must be new and cannot traverse symlinks")
    ignored = subprocess.run(["git", "check-ignore", "--quiet", str(output)], cwd=repository).returncode == 0
    if not ignored:
        raise ValueError("Private benchmark output is not ignored by Git")
    private_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".historical-", dir=private_root) as temporary:
        stage = Path(temporary) / "results"
        stage.mkdir(mode=0o700)
        for name, value in (("report.json", report), ("private-text-manifest.json", private)):
            path = stage / name
            path.write_bytes(_encode(value))
            path.chmod(0o600)
        stage.rename(output)
    return {"output": str(output), "report_sha256": _hash(_encode(report)),
            "private_manifest_sha256": _hash(_encode(private))}
