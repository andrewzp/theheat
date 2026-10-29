"""Connected offline global-readiness journey over invented, labelled exports.

Every export below is produced by an existing codec (product contracts, the real
rainfall recorder, the GHCN six-station supply path, the episode binding validator,
report review projection, coverage evaluation and the portfolio planner). The
choices are invented fixtures, not human decisions or scientific labels.
"""

from copy import deepcopy
from datetime import date
import hashlib
import json
from random import Random
import subprocess
import sys
from types import SimpleNamespace
import uuid

import pytest

from src.data import source_product_contracts as products
from src.data.gpm_imerg import opportunity_population
from src.data.open_meteo import CountryRecord, ExtremeSignalBundle
from src.editorial.portfolio import DIMENSIONS, PlanningCandidate, plan_portfolio
from src.editorial.report_development import review_projection
from src.evaluation import global_readiness as readiness
from src.storage import physical_events
from src.storage import scientific_supply as supply_codec
from src.storage.retained_reports import TIME_KEYS
from tests import test_coverage_evaluation as coverage_fixture
from tests.test_ghcn_scientific_supply import supply, supply_inputs  # noqa: F401
from tests.test_rainfall_opportunity import _grid_trace, population

CUTOFF = "2026-10-13T00:00:00Z"
EPISODE = "ep1:cyclone:nhc:AL012026"
REVISION = hashlib.sha256(b"invented episode revision").hexdigest()
NEWER = hashlib.sha256(b"invented later revision").hexdigest()
REPORT_SHA = "b" * 64  # the coverage fixture's invented decision subject
SUPPLY_RUN = str(uuid.UUID(int=11))


def episode(revision=REVISION):
    return physical_events.validate_binding(dict(
        schema_version=1, episode_id=EPISODE, revision_sha256=revision, identity_class="source_scoped",
        source_assertion_refs=[hashlib.sha256(f"assertion-{revision}".encode()).hexdigest()]))


def report(*, lineage="fixture:report1", sha=REPORT_SHA, language="en", linked=True, limits=("Invented data only",)):
    raw = b"Invented authority bulletin refers to AL012026."
    times = dict.fromkeys(TIME_KEYS)
    times.update(event_start=dict(original="October11", utc=None, date="2026-10-11", precision="calendar", timezone=None),
                 event_end=dict(original="October11", utc=None, date="2026-10-11", precision="calendar", timezone=None))
    claim = dict(claim_id="claim1", kind="reported_impact", summary="Invented report claim", anchors=[dict(
        artifact_id=hashlib.sha256(b"artifact" + raw).hexdigest(), content_sha256=hashlib.sha256(raw).hexdigest(),
        start=0, end=len(raw), text=raw.decode())], original_language=language,
        translation=dict(text=None, status="not_needed" if language == "en" else "unreviewed", decision_ref=None),
        source_review=dict(status="pending", decision_ref=None), attribution="Invented agency", times=times,
        quantity=dict(value=4, unit="people", operator="reported", scope="cumulative"),
        geography=dict(reported_scope="Invented footprint", role="reported_footprint", map_marker=None, geometry=None),
        identity_reference=dict(authority="nhc", source_id="AL012026", anchor_index=0),
        holds=["impact_not_independently_adjudicated"])
    document = dict(schema_version=1, lineage_id=lineage, previous_report_sha256=None, publisher="Invented agency",
        source_url="https://example.test/report", hazards=["cyclone"], original_language=language,
        artifact_refs=[claim["anchors"][0]["artifact_id"]], upstream_lineage_refs=[], claims=[claim],
        limits=list(limits), captured_at="2026-10-11T12:00:00Z", reference_review=dict(
            candidate_id=None, adjudication="pending_human_and_source_review", benchmark_eligible=False,
            importance=None, detection_deadline=None, bot_match="not_evaluated"), legacy_metadata=None)
    projection = review_projection(SimpleNamespace(canonical_sha256=sha), document)
    if linked:
        # The exact shape resolve_story_context records; its PG resolution is not run here.
        projection["development_status"] = "evidence_review_required"
        projection["related_story"] = dict(episode_id=EPISODE, episode_head=REVISION,
                                           association_status="source_identity_reference_only",
                                           time_compatibility="source_calendar_compatibility_only")
    return projection


def coverage_result():
    ref = dict(lineage_id="fixture:report1", report_sha256=REPORT_SHA, claim_ids=["claim1"])
    document = coverage_fixture.reference_document(ref)
    retained = coverage_fixture.declare(document, coverage_fixture.decision_document())
    return coverage_fixture.evaluate(document, decisions=[retained])


def plan(revision=REVISION, *, missing=("novelty",)):
    binding = dict(event_group_id=EPISODE, event_revision_sha256=revision,
                   opportunity_id=hashlib.sha256(b"opportunity").hexdigest(),
                   bundle_sha256=hashlib.sha256(b"bundle").hexdigest(), policy_sha256="f" * 64)
    dimensions = {key: None if key in missing else dict(score=3, reason="Invented operator assessment")
                  for key in DIMENSIONS}
    return plan_portfolio([PlanningCandidate(binding, "cyclone", ("country:AA",), dimensions)], writing_attempts=1)


def supply_envelope(bundles, countries, metrics):
    rows = [supply_codec._row(b, ExtremeSignalBundle, decoding=False) for b in bundles]
    country_rows = [supply_codec._row(c, CountryRecord, decoding=False) for c in countries]
    # The runner adds the run status; the retention test supplies it the same way.
    metrics = {**metrics, "status": "success", "threshold_verification": "success"}
    outcome = supply_codec._outcome(metrics) | {"supply_empty": not bundles}
    return supply_codec.detached_json(dict(
        schema_version=1, source="ghcn-daily", supply_run_id=SUPPLY_RUN, captured_at="2026-10-11T12:00:00Z",
        orchestrator_run_id="run_alerts_fixture", producer_contract=dict(codec="ghcn-supply-v1", git_commit="a" * 40),
        source_outcome=outcome, bundles=rows, country_records=country_rows))


@pytest.fixture
def parts(supply):  # noqa: F811
    rows = population(6)
    return {
        "products": ("source_products", products.product_contract_document()),
        "trace": ("rainfall_opportunity", _grid_trace(rows, date(2026, 6, 5), read={0, 1}, run_id="run_alerts_g11")),
        "population": ("rainfall_opportunity", opportunity_population(rows)),
        "supply": ("scientific_supply", supply_envelope(*supply)),
        "episode": ("physical_episode", episode()),
        "report": ("report_development", report()),
        "untranslated": ("report_development", report(lineage="fixture:report2", sha="c" * 64, language="th",
                                                      linked=False)),
        "coverage": ("coverage_assessment", coverage_result()),
        "portfolio": ("portfolio", plan()),
    }


def envelope(parts, *names, cutoff=CUTOFF):
    chosen = names or tuple(parts)
    return {"schema_version": 1, "assessment_cutoff": cutoff,
            "components": [{"component_type": parts[n][0], "export": deepcopy(parts[n][1])} for n in chosen]}


def by_identity(result):
    return {row["identity"]: row for row in result["components"] if row["identity"]}


def joins(result):
    return {(j["from"], j["relation"], j["to"]): j["disposition"] for j in result["joins"]}


def test_connected_offline_cli_journey_produces_bounded_packet_with_concrete_reasons(parts, tmp_path):
    tmp_path = tmp_path.resolve()
    source = tmp_path / "envelope.json"
    source.write_text(json.dumps(envelope(parts)))
    out = tmp_path / "packet"
    command = [sys.executable, "scripts/summarize_global_readiness.py", "--input", str(source), "--output-dir", str(out)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    result = json.loads((out / "readiness.json").read_text())
    text = (out / "review.txt").read_text()
    assert (out / "readiness.json").stat().st_size <= readiness.MAX_OUTPUT_BYTES
    assert all(ch == "\n" or 32 <= ord(ch) < 127 for ch in text)
    rows = by_identity(result)
    contracts = "contracts:" + parts["products"][1]["contracts_sha256"]
    assert rows[contracts]["status"] == "current"
    assert rows["trace:run_alerts_g11"]["status"] == "current"
    supply_row = rows["supply:" + SUPPLY_RUN]
    assert supply_row["status"] == "current" and supply_row["facts"]["station_count"] == 6
    assert supply_row["facts"]["publication_caps_applied"] is False
    assert rows[f"episode:{EPISODE}@{REVISION}"]["status"] == "current"
    assert rows[f"report:fixture:report1@{REPORT_SHA}"]["status"] == "held"
    assert "report_claims_not_promoted" in rows[f"report:fixture:report1@{REPORT_SHA}"]["reasons"]
    coverage_id = next(i for i in rows if i.startswith("coverage:"))
    portfolio_id = next(i for i in rows if i.startswith("portfolio:"))
    assert rows[coverage_id]["reasons"] == ["reference_not_qualified"]
    assert rows[portfolio_id]["reasons"] == ["not_human_calibrated"]
    links = joins(result)
    candidate = rows[portfolio_id]["facts"]["candidates"][0]["candidate_id"]
    population_sha = parts["population"][1]["sha256"]
    assert links[("trace:run_alerts_g11", "product_contract", "gpm_imerg.imerg_late_grid_datapool")] == "exact"
    assert links[("trace:run_alerts_g11", "canonical_population", f"population:{population_sha}")] == "exact"
    assert links[("supply:" + SUPPLY_RUN, "product_contract", "open_meteo_extreme_signals.ghcn_daily")] == "exact"
    assert links[(f"episode:{EPISODE}@{REVISION}", "product_contract", "nhc.current_storms_index")] == "exact"
    assert links[(f"report:fixture:report1@{REPORT_SHA}", "physical_episode", f"episode:{EPISODE}@{REVISION}")] == "exact"
    assert links[(f"report:fixture:report2@{'c' * 64}", "physical_episode", None)] == "not_linked"
    assert links[(f"{coverage_id}#fixture-unit", "report_revision", f"report:fixture:report1@{REPORT_SHA}")] == "exact"
    assert links[(f"{portfolio_id}#{candidate}", "physical_episode", f"episode:{EPISODE}@{REVISION}")] == "exact"
    states = result["evidence_states"]
    assert states["missing"] == [] and states["dependency_blocked"] == []
    assert states["untranslated"] == [f"report:fixture:report2@{'c' * 64}#claim1"]
    assert states["grouping_unresolved"] == [f"{coverage_id}#fixture-unit"]
    assert result["global_recall"] is None and result["coverage_denominator"] is None
    assert all(row["status"] == "open" for row in result["unmet_requirements"].values())
    assert set(result["unmet_requirements"]) == set(readiness.PACKAGES)
    assert "denominator_not_qualified" in result["unmet_requirements"]["P22"]["unmet"]
    assert "not_human_calibrated" in result["unmet_requirements"]["P23"]["unmet"]
    assert result["rainfall_opportunity"]["label"] == "measured_rainfall_opportunity_not_global_recall"
    assert result["rainfall_opportunity"]["achieved_revisit_sla"] is None
    packet = result["human_review_packet"]
    assert packet["reviewer_identity"] is None and packet["creates_votes_labels_translations_or_approvals"] is False
    assert all(item["decision"] is None and item["decided_by"] is None for item in packet["decisions_needed"])
    questions = {(item["subject"], item["question"]) for item in packet["decisions_needed"]}
    assert (f"report:fixture:report2@{'c' * 64}#claim1", "translation_review_pending") in questions
    assert (f"{coverage_id}#fixture-unit", "grouping_unresolved") in questions
    assert (f"{portfolio_id}#{candidate}", "dimension_unassessed:novelty") in questions
    assert (f"{portfolio_id}#{candidate}", "independent_human_rank_missing") in questions
    assert "Global recall: null" in text
    again = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert again.returncode == 2 and json.loads(again.stdout) == {"error": "FileExistsError"}


def test_component_order_does_not_change_the_packet(parts):
    first = readiness.assess(envelope(parts))
    for seed in range(3):
        shuffled = envelope(parts)
        Random(seed).shuffle(shuffled["components"])
        assert readiness.assess(shuffled) == first


def test_repeated_copies_count_once_and_conflicting_identities_are_held(parts):
    value = envelope(parts)
    value["components"].append(deepcopy(value["components"][4]))  # exact episode copy
    changed = report(limits=("Invented data only", "Second capture"))
    value["components"].append({"component_type": "report_development", "export": changed})
    result = readiness.assess(value)
    statuses = sorted(row["status"] for row in result["components"] if row["component_type"] == "physical_episode")
    assert statuses == ["copy", "current"]
    conflicts = [row for row in result["components"] if row["identity"] == f"report:fixture:report1@{REPORT_SHA}"]
    assert {row["status"] for row in conflicts} == {"conflict_held"} and len(conflicts) == 2
    coverage_id = next(row["identity"] for row in result["components"] if row["component_type"] == "coverage_assessment")
    link = joins(result)[(f"{coverage_id}#fixture-unit", "report_revision", f"report:fixture:report1@{REPORT_SHA}")]
    assert link == "held_dependency"


def test_stale_and_ambiguous_revisions_never_join_as_current(parts):
    parts = dict(parts, episode=("physical_episode", episode(NEWER)))
    result = readiness.assess(envelope(parts))
    links = joins(result)
    target = f"episode:{EPISODE}@{REVISION}"
    assert links[(f"report:fixture:report1@{REPORT_SHA}", "physical_episode", target)] == "stale_binding"
    assert any(f"-> {target}" in item for item in result["evidence_states"]["corrected_superseded"])
    both = envelope(parts)
    both["components"].append({"component_type": "physical_episode", "export": episode()})
    result = readiness.assess(both)
    held = [row for row in result["components"] if row["component_type"] == "physical_episode"]
    assert {row["status"] for row in held} == {"held"} and all("revision_order_unknown" in r["reasons"] for r in held)
    assert joins(result)[(f"report:fixture:report1@{REPORT_SHA}", "physical_episode", target)] == "held_dependency"
    lineage = envelope(parts)
    lineage["components"].append({"component_type": "report_development", "export": report(sha="d" * 64)})
    result = readiness.assess(lineage)
    coverage_id = next(row["identity"] for row in result["components"] if row["component_type"] == "coverage_assessment")
    assert joins(result)[(f"{coverage_id}#fixture-unit", "report_revision",
                          f"report:fixture:report1@{REPORT_SHA}")] == "held_dependency"


def test_unknown_translation_quiet_periods_and_unqualified_coverage_stay_unknown(parts):
    parts = dict(parts, report=("report_development", report(language="und", linked=False)))
    result = readiness.assess(envelope(parts))
    assert f"report:fixture:report1@{REPORT_SHA}#claim1" in result["evidence_states"]["untranslated"]
    unmet = result["unmet_requirements"]
    assert "independent_events_quiet_periods_missing" in unmet["P22"]["unmet"]
    assert "reference_gap_selection_blocked_unqualified_baseline" in unmet["P17b"]["unmet"]
    coverage = next(row for row in result["components"] if row["component_type"] == "coverage_assessment")
    assert coverage["facts"]["reference_status"] == "not_qualified" and coverage["facts"]["metrics_null"] is True
    assert result["global_recall"] is None and result["coverage_denominator"] is None


def test_wholly_missing_inputs_and_unsupported_sources_are_explicit(parts):
    empty = readiness.assess({"schema_version": 1, "assessment_cutoff": CUTOFF, "components": []})
    assert empty["evidence_states"]["missing"] == sorted(readiness.COMPONENT_TYPES)
    assert "product_contracts_missing" in empty["unmet_requirements"]["P17"]["unmet"]
    assert empty["global_recall"] is None and empty["rainfall_opportunity"] is None
    tampered = deepcopy(parts["products"][1])
    tampered["products"][0]["data_kind"] = "observed_station"
    other_source = deepcopy(parts["supply"][1])
    other_source["source"] = "invented-gsod"
    value = envelope(parts)
    value["components"] += [{"component_type": "source_products", "export": tampered},
                            {"component_type": "scientific_supply", "export": other_source},
                            {"component_type": "national_service_pilot", "export": {"claimed": "qualified"}}]
    result = readiness.assess(value)
    unsupported = [row for row in result["components"] if row["status"] == "unsupported"]
    assert sorted(r["reasons"][0] for r in unsupported) == ["source_product_export_digest", "unsupported_component_type",
                                                             "unsupported_supply_source"]
    assert all(row["identity"] is None for row in unsupported)
    assert len(result["evidence_states"]["unsupported"]) == 3


def test_caller_labels_cannot_overrule_missing_evidence(parts):
    qualified = deepcopy(parts["coverage"][1])
    qualified["reference_readiness"]["status"] = "qualified"
    calibrated = deepcopy(parts["portfolio"][1])
    calibrated["calibration_status"] = "human_calibrated"
    granted = deepcopy(parts["products"][1])
    granted["claim_permission_granted"] = True
    body = {k: v for k, v in granted.items() if k != "contracts_sha256"}
    granted["contracts_sha256"] = readiness.digest(body)
    value = {"schema_version": 1, "assessment_cutoff": CUTOFF, "components": [
        {"component_type": "coverage_assessment", "export": qualified},
        {"component_type": "portfolio", "export": calibrated},
        {"component_type": "source_products", "export": granted}]}
    result = readiness.assess(value)
    assert {row["status"] for row in result["components"]} == {"unsupported"}
    assert sorted(row["reasons"][0] for row in result["components"]) == [
        "invalid_coverage_assessment", "portfolio_plan_mismatch", "source_product_export_permission"]


def test_later_knowledge_is_held_against_an_earlier_cutoff(parts):
    result = readiness.assess(envelope(parts, cutoff="2026-10-11T00:00:00Z"))
    rows = by_identity(result)
    coverage_id = next(i for i in rows if i.startswith("coverage:"))
    assert "after_assessment_cutoff" in rows[coverage_id]["reasons"]
    assert "after_assessment_cutoff" in rows["supply:" + SUPPLY_RUN]["reasons"]
    early = readiness.assess(envelope(parts, cutoff="2026-06-04T00:00:00Z"))
    assert "after_assessment_cutoff" in by_identity(early)["trace:run_alerts_g11"]["reasons"]
    assert early["rainfall_opportunity"] is None


def test_six_station_supply_is_complete_and_order_independent(parts, supply):  # noqa: F811
    bundles, countries, metrics = supply
    reversed_supply = supply_envelope(list(reversed(bundles)), countries, metrics)
    one = readiness.assess(envelope(parts, "supply"))
    two = readiness.assess(envelope(dict(parts, supply=("scientific_supply", reversed_supply)), "supply"))
    stations = [row["facts"]["stations"] for row in (*one["components"], *two["components"])]
    assert stations[0] == stations[1] and len(stations[0]) == 6
    assert one["unmet_requirements"]["P18"]["evidence_components"] == ["supply:" + SUPPLY_RUN]


@pytest.mark.parametrize("change", [
    {"extra": 1}, {"schema_version": True}, {"schema_version": "1"}, {"schema_version": 2},
    {"assessment_cutoff": "2026-10-13T00:00:00"}, {"assessment_cutoff": "2026-10-13T00:00:00+02:00"},
    {"components": [{"component_type": "portfolio"}]}, {"components": [{}] * 129},
    {"components": {"component_type": "portfolio", "export": {}}},
])
def test_invalid_envelopes_refuse_with_a_bounded_code(change):
    value = {"schema_version": 1, "assessment_cutoff": CUTOFF, "components": []} | change
    with pytest.raises(readiness.ReadinessError) as caught:
        readiness.assess(value)
    assert str(caught.value).replace("_", "").isalnum()


def test_cli_refuses_duplicate_keys_nonfinite_numbers_and_symlinks(tmp_path):
    tmp_path = tmp_path.resolve()
    cases = {"dup.json": '{"schema_version": 1, "schema_version": 1}', "nan.json": '{"x": NaN}'}
    for name, body in cases.items():
        (tmp_path / name).write_text(body)
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"schema_version": 1, "assessment_cutoff": CUTOFF, "components": []}))
    (tmp_path / "link.json").symlink_to(good)
    for name, code in (("dup.json", "duplicate_json_key"), ("nan.json", "nonfinite_json_number"),
                       ("link.json", "symlinked_path")):
        done = subprocess.run([sys.executable, "scripts/summarize_global_readiness.py", "--input", str(tmp_path / name)],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 2 and json.loads(done.stdout) == {"error": code}


def test_plain_text_escapes_control_characters_and_markup():
    result = readiness.assess({"schema_version": 1, "assessment_cutoff": CUTOFF, "components": []})
    result["components"] = [{"component_type": "x\u001b[31m", "identity": "<img src=x>\u0007‮", "status": "held",
                             "reasons": ["a\nb"], "export_sha256": "0" * 64}]
    text = readiness.render_text(result)
    assert "\u001b" not in text and "\u0007" not in text and "‮" not in text
    assert "\\u001b" in text and "a\\nb" in text


def test_assessment_performs_no_network_or_file_access(parts, tmp_path):
    source = tmp_path.resolve() / "envelope.json"
    source.write_text(json.dumps(envelope(parts)))
    code = f'''
import builtins, json, socket
from src.evaluation import global_readiness as readiness
value = json.loads(open({str(source)!r}).read())
def forbidden(*args, **kwargs): raise AssertionError("I/O forbidden during assessment")
socket.socket = forbidden
builtins.open = forbidden
result = readiness.assess(value)
assert result["global_recall"] is None
'''
    subprocess.run([sys.executable, "-c", code], check=True, timeout=120)


# G11-R1/R3 repairs (invented exports; never weather truth or human review).

def _rehash_products(document):
    body = {key: value for key, value in document.items() if key != "contracts_sha256"}
    return {**body, "contracts_sha256": readiness.digest(body)}


def test_r1_cleared_product_summaries_cannot_hide_null_required_evidence(parts):
    """S3-R3: a rehashed export with cleared summaries never yields P17 unmet=[]."""
    cleared = deepcopy(parts["products"][1])
    cleared["unmet_criteria"], cleared["missing_work"] = [], []
    value = {"schema_version": 1, "assessment_cutoff": CUTOFF,
             "components": [{"component_type": "source_products", "export": _rehash_products(cleared)}]}
    result = readiness.assess(value)
    p17 = result["unmet_requirements"]["P17"]["unmet"]
    assert p17 and "product_contracts_missing" not in p17
    row = result["components"][0]
    assert row["status"] == "unsupported" and row["reasons"] == ["source_product_export_summary"]
    valid = readiness.assess(envelope(parts, "products"))
    unmet = valid["unmet_requirements"]["P17"]["unmet"]
    assert {"provider_cadence_unknown", "current_availability_unverified", "restriction_enforcement_unresolved",
            "unresolved_or_retired_legs_remain"} <= set(unmet)


def _components(*pairs):
    return {"schema_version": 1, "assessment_cutoff": CUTOFF,
            "components": [{"component_type": kind, "export": deepcopy(value)} for kind, value in pairs]}


def test_r3_conflicting_capture_of_one_revision_keeps_the_lineage_ambiguous(parts):
    """S3-R1: conflict-held A plus B must not make B current or exact."""
    a = episode()
    conflict = deepcopy(a)
    conflict["source_assertion_refs"] = [hashlib.sha256(b"invented other assertion").hexdigest()]
    b = episode(NEWER)
    linked = report()
    linked["related_story"]["episode_head"] = NEWER
    planned = plan(NEWER)
    pairs = [("physical_episode", a), ("physical_episode", conflict), ("physical_episode", b),
             ("report_development", linked), ("portfolio", planned)]
    outcomes = set()
    for seed in range(6):
        shuffled = list(pairs)
        Random(seed).shuffle(shuffled)
        result = readiness.assess(_components(*shuffled))
        newer = next(row for row in result["components"] if row["identity"] == f"episode:{EPISODE}@{NEWER}")
        assert newer["status"] == "held" and "revision_order_unknown" in newer["reasons"]
        target = f"episode:{EPISODE}@{NEWER}"
        episode_joins = {j["from"].split("#")[0].split(":")[0]: j["disposition"] for j in result["joins"]
                         if j["relation"] == "physical_episode" and j["to"] == target}
        assert episode_joins == {"report": "held_dependency", "portfolio": "held_dependency"}
        outcomes.add(json.dumps(result, sort_keys=True))
    assert len(outcomes) == 1


@pytest.mark.parametrize("decision_ref", [None, "decision:invented-not-a-trusted-reference"])
def test_r3_a_human_reviewed_translation_label_is_not_proof_of_review(parts, decision_ref):
    """S3-R2: the caller's label and removed holds never clear a translation hold."""
    thai = report(language="th", linked=False)
    thai["claims"][0]["translation"].update(status="human_reviewed", text="Invented translation",
                                            decision_ref=decision_ref)
    for part in (thai, *thai["claims"]):
        part["holds"] = [hold for hold in part["holds"] if hold != "translation_review_pending"]
    result = readiness.assess(_components(("report_development", thai)))
    subject = f"report:fixture:report1@{REPORT_SHA}#claim1"
    assert result["evidence_states"]["untranslated"] == [subject]
    questions = {(item["subject"], item["question"]) for item in result["human_review_packet"]["decisions_needed"]}
    assert (subject, "translation_review_unverified") in questions
    assert all(item["decision"] is None and item["decided_by"] is None
               for item in result["human_review_packet"]["decisions_needed"])
    english = report(linked=False)
    clean = readiness.assess(_components(("report_development", english)))
    assert clean["evidence_states"]["untranslated"] == []


def test_r3_malformed_supplied_fields_are_bounded_holds_not_tracebacks(parts):
    """S3-R4: holds containing a dictionary and a malformed rainfall field."""
    bad_holds = report()
    bad_holds["holds"].append({})
    bad_claim = report(lineage="fixture:report3", sha="e" * 64)
    bad_claim["claims"][0]["holds"].append(["nested"])
    trace = deepcopy(parts["trace"][1])
    trace["trace_status"] = []
    result = readiness.assess(_components(("report_development", bad_holds), ("report_development", bad_claim),
                                          ("rainfall_opportunity", trace), parts["episode"]))
    unsupported = sorted((row["component_type"], row["reasons"][0]) for row in result["components"]
                         if row["status"] == "unsupported")
    assert unsupported == [("rainfall_opportunity", "trace_status"),
                           ("report_development", "invalid_report_projection"),
                           ("report_development", "invalid_report_projection")]
    assert by_identity(result)[f"episode:{EPISODE}@{REVISION}"]["status"] == "current"


def test_r3_deeply_nested_json_is_a_bounded_envelope_refusal(tmp_path):
    raw = b"[" * 50000 + b"]" * 50000
    with pytest.raises(readiness.ReadinessError, match="input_structure_bound"):
        readiness.strict_loads(raw)
    nested: list = []
    for _ in range(500):
        nested = [nested]
    with pytest.raises(readiness.ReadinessError, match="input_structure_bound"):
        readiness.assess({"schema_version": 1, "assessment_cutoff": CUTOFF,
                          "components": [{"component_type": "portfolio", "export": nested}]})
    source = tmp_path.resolve() / "deep.json"
    source.write_bytes(raw)
    done = subprocess.run([sys.executable, "scripts/summarize_global_readiness.py", "--input", str(source)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and json.loads(done.stdout) == {"error": "input_structure_bound"}
    assert "Traceback" not in done.stderr


def test_r3_more_populations_than_one_audit_accepts_never_truncate_or_crash(parts):
    """S3-R4: 65 distinct populations plus one trace in a valid envelope."""
    rows = population(6)
    others = [opportunity_population(population(2, label=f"Other{i}")) for i in range(65)]
    value = _components(*(("rainfall_opportunity", pop) for pop in others), parts["trace"], parts["population"])
    assert len(value["components"]) <= readiness.MAX_COMPONENTS
    result = readiness.assess(value)
    section = result["rainfall_opportunity"]
    assert section["status"] == "audited" and section["populations_supplied"] == 66
    assert section["populations_audited"] == [opportunity_population(rows)["sha256"]]
    # More referenced populations than one audit accepts: held, never truncated. A valid
    # 128-component envelope cannot reach 65 referenced populations, so the bound is lowered.
    second = _grid_trace(population(2, label="Second"), date(2026, 6, 6), read={0}, run_id="run_alerts_second")
    value = _components(parts["trace"], parts["population"], ("rainfall_opportunity", second),
                        ("rainfall_opportunity", opportunity_population(population(2, label="Second"))))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(readiness.rainfall, "MAX_AUDIT_POPULATIONS", 1)
        held = readiness.assess(value)["rainfall_opportunity"]
    assert held["status"] == "held" and held["reason"] == "audit_population_bound"
    assert held["observed_complete_windows"] is None and held["global_recall"] is None
    assert len(held["populations_audited"]) == 2


def test_r3_supplied_conflicting_or_unsupported_is_never_reported_missing(parts):
    """S3-R5: presence is separate from usability."""
    rep = report()
    other = deepcopy(rep)
    other["original_language"] = "fr"
    qualified = deepcopy(parts["coverage"][1])
    qualified["reference_readiness"]["status"] = "qualified"
    result = readiness.assess(_components(("report_development", rep), ("report_development", other),
                                          ("coverage_assessment", qualified)))
    states = result["evidence_states"]
    assert "report_development" not in states["missing"] and "coverage_assessment" not in states["missing"]
    assert states["component_presence"]["report_development"] == "supplied_conflicting"
    assert states["component_presence"]["coverage_assessment"] == "supplied_unsupported"
    assert states["component_presence"]["portfolio"] == "absent" and "portfolio" in states["missing"]
    unmet = result["unmet_requirements"]
    assert "report_development_supplied_conflicting" in unmet["P21"]["unmet"]
    assert "report_development_missing" not in unmet["P21"]["unmet"]
    assert "coverage_assessment_supplied_unsupported" in unmet["P22"]["unmet"]
    assert "portfolio_missing" in unmet["P23"]["unmet"]
    questions = {item["question"] for item in result["human_review_packet"]["decisions_needed"]}
    assert "conflicting_exports_same_identity" in questions
    assert "supplied_export_unsupported:invalid_coverage_assessment" in questions


def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location("summarize_global_readiness_cli",
                                                  "scripts/summarize_global_readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_r3_actual_encoded_outputs_are_bounded_before_anything_is_created(parts, tmp_path):
    """S3-R6: the 500,000-character U+0800 language fits compact UTF-8 but not the written JSON."""
    tmp_path = tmp_path.resolve()
    wide = report(linked=False)
    wide["original_language"] = "ࠀ" * 500_000
    source = tmp_path / "wide.json"
    source.write_text(json.dumps(_components(("report_development", wide))))
    out = tmp_path / "wide-packet"
    done = subprocess.run([sys.executable, "scripts/summarize_global_readiness.py", "--input", str(source),
                           "--output-dir", str(out)], capture_output=True, text=True, timeout=120)
    if done.returncode == 0:
        for name in ("readiness.json", "review.txt"):
            assert (out / name).stat().st_size <= readiness.MAX_OUTPUT_BYTES, name
    else:
        assert json.loads(done.stdout) == {"error": "output_too_large"} and not out.exists()
    result = readiness.assess(_components(("report_development", wide)))
    assert result["components"][0]["status"] == "unsupported"


def test_r3_cli_refuses_an_oversized_written_body_without_creating_output(parts, tmp_path, monkeypatch, capsys):
    tmp_path = tmp_path.resolve()
    source = tmp_path / "envelope.json"
    source.write_text(json.dumps(envelope(parts)))
    result = readiness.assess(envelope(parts))
    compact = len(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    written = len(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=1).encode()) + 1
    assert compact < written
    cli = _cli()
    monkeypatch.setattr(readiness, "MAX_OUTPUT_BYTES", compact + 1)  # compact fits, written JSON does not
    out = tmp_path / "packet"
    for argv in (["--input", str(source), "--output-dir", str(out)], ["--input", str(source)]):
        assert cli.main(argv) == 2
        assert json.loads(capsys.readouterr().out) == {"error": "output_too_large"}
        assert not out.exists()


@pytest.fixture
def swap_root(tmp_path):
    base = tmp_path.resolve()
    for name in ("work", "evil"):
        (base / name).mkdir()
    good = {"schema_version": 1, "assessment_cutoff": CUTOFF, "components": []}
    bad = {"schema_version": 1, "assessment_cutoff": "2026-01-01T00:00:00Z", "components": []}
    (base / "work" / "envelope.json").write_text(json.dumps(good))
    (base / "evil" / "envelope.json").write_text(json.dumps(bad))
    return base


def _swap(base):
    import os
    os.rename(base / "work", base / "work-moved")
    (base / "work").symlink_to(base / "evil")


def test_r3_parent_replaced_after_the_check_cannot_redirect_the_read(swap_root, monkeypatch, capsys):
    """S3-R7: the input is opened relative to a held directory descriptor."""
    import os
    real_open = os.open
    swapped = []

    def open_then_swap(path, flags, *args, **kwargs):
        if os.fspath(path).endswith("envelope.json") and not swapped:
            swapped.append(True)
            _swap(swap_root)
        return real_open(path, flags, *args, **kwargs)

    cli = _cli()
    monkeypatch.setattr(os, "open", open_then_swap)
    assert cli.main(["--input", str(swap_root / "work" / "envelope.json")]) == 0
    assert swapped and json.loads(capsys.readouterr().out)["assessment_cutoff"] == CUTOFF


def test_r3_parent_replaced_after_the_check_cannot_redirect_the_write(swap_root, monkeypatch, capsys):
    """S3-R7: the private output directory is created relative to a held parent descriptor."""
    import os
    real_mkdir = os.mkdir
    swapped = []

    def mkdir_then_swap(path, *args, **kwargs):
        if os.fspath(path).endswith("packet") and not swapped:
            swapped.append(True)
            _swap(swap_root)
        return real_mkdir(path, *args, **kwargs)

    cli = _cli()
    monkeypatch.setattr(os, "mkdir", mkdir_then_swap)
    source = swap_root / "evil" / "envelope.json"  # read from a separate, unswapped parent
    source.rename(swap_root / "input.json")
    assert cli.main(["--input", str(swap_root / "input.json"), "--output-dir", str(swap_root / "work" / "packet")]) == 0
    capsys.readouterr()
    assert swapped and not (swap_root / "evil" / "packet").exists()
    written = swap_root / "work-moved" / "packet"
    assert sorted(p.name for p in written.iterdir()) == ["readiness.json", "review.txt"]
    assert oct(written.stat().st_mode & 0o777) == "0o700"
    assert all(oct(p.stat().st_mode & 0o777) == "0o600" for p in written.iterdir())


def test_r3_cli_refuses_fifo_static_symlinked_parents_and_collisions(tmp_path):
    import os
    base = tmp_path.resolve()
    good = base / "good.json"
    good.write_text(json.dumps({"schema_version": 1, "assessment_cutoff": CUTOFF, "components": []}))
    fifo = base / "envelope.fifo"
    os.mkfifo(fifo)
    (base / "real").mkdir()
    (base / "linked").symlink_to(base / "real")
    script = "scripts/summarize_global_readiness.py"
    cases = [(["--input", str(fifo)], "input_not_regular"),
             (["--input", str(base)], "input_not_regular"),
             (["--input", str(good), "--output-dir", str(base / "linked" / "packet")], "symlinked_path"),
             (["--input", str(good), "--output-dir", str(good)], "FileExistsError")]
    for argv, code in cases:
        try:
            done = subprocess.run([sys.executable, script, *argv], capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            pytest.fail(f"readiness CLI blocked on {argv}")
        assert done.returncode == 2 and json.loads(done.stdout) == {"error": code}, (argv, done.stdout)
    assert not (base / "real" / "packet").exists()
