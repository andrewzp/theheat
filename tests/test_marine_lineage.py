"""Invented source-to-review lineage; no external requests or historical claims."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
import json
from unittest.mock import Mock

import pytest

from src import state
from src.editorial import marine_evidence as marine, synthesis
from src.editorial.policy import current_editorial_policy, source_manifest
from src.editorial.revisions import fingerprint
from src.two_bot import fact_check, pipeline, check_requests
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.synthesis import build_synthesis_bundle
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests import crw_fixtures, coral_point_fixtures
from tests import marine_fixtures
from tests.marine_fixtures import sst_reading, coral_reading, qualified_state, bundle

marine_clock = marine_fixtures.marine_clock
from tests.two_bot.conftest import _state_with_memory, configured_pipeline_providers
from tests.two_bot.test_candidate_derivation import packet

pytestmark = pytest.mark.usefixtures("marine_clock")
FACTUAL = "Great Nicobar heat stress reached 8.25 °C-weeks on June 15; the Bay of Bengal SST anomaly was +2.2°C on the 14th."
CAUSAL = "The same heatwave is driving coral bleaching in the Bay of Bengal."


def select(s, kind="sst_anomaly", region="bay_of_bengal", diagnostics=None):
    return marine.select_component(s, kind, region, marine.now_utc(), diagnostics=diagnostics)


def test_complete_source_to_bundle_detached_and_dates_explicit(monkeypatch):
    s = qualified_state(monkeypatch)
    before = deepcopy(s)
    signals = synthesis.detect_marine_compound(s)
    sig = signals[0]
    assert sig.components["sst_tier"] == 0  # Quiet individually, eligible for this comparison.
    assert sig.components["coral_dhw_tier"] == 8
    value = build_synthesis_bundle(sig.components["marine_payload"])
    assert audit_story_bundle(value).prompt_ready
    assert value.when == "2026-06-16"
    facts = {f["label"]: f["value"] for f in value.current_facts}
    assert facts["coral_valid_date"] == "2026-06-15"
    assert facts["sst_valid_date"] == "2026-06-14"
    assert value.headline_metric["value"] == 8.25
    assert "sst_reference_climatology" in value.historical_context
    assert "not a shared measurement footprint" in value.historical_context["association"]["value"]
    value.raw_signal_dump["components"]["coral"]["marine_source"]["reading"]["provenance"]["dhw_value"] = 99
    sig.components["marine_payload"]["components"]["sst_anomaly"]["marine_source"]["reading"]["anomaly_c"] = 99
    assert s == before


def test_record_is_detached_and_duplicate_identity_is_exact(monkeypatch):
    reading = sst_reading(monkeypatch)
    s = deepcopy(state.DEFAULT_STATE)
    assert marine.record_reading(s, "sst_anomaly", reading) == "retained"
    original = deepcopy(s)
    assert marine.record_reading(s, "sst_anomaly", reading) == "unchanged"
    reading.provenance["mean_anomaly_c"] = 99
    assert s == original
    fresh = sst_reading(monkeypatch)
    s["synthesis_components"]["sst_anomalies"]["bay_of_bengal"][0]["at"] = "2026-06-15T00:00:00Z"
    assert marine.record_reading(s, "sst_anomaly", fresh) == "component_identity_conflict"
    assert select(s) is None


def test_reacquisition_changes_identity_and_conflicting_values_survive_merge(monkeypatch, marine_clock):
    old = sst_reading(monkeypatch)
    a, b = deepcopy(state.DEFAULT_STATE), deepcopy(state.DEFAULT_STATE)
    marine.record_reading(a, "sst_anomaly", old)
    marine_clock.current += timedelta(hours=1)
    same = sst_reading(monkeypatch)
    marine.record_reading(b, "sst_anomaly", same)
    merged = {"synthesis_components": state._merge_synthesis_components(a["synthesis_components"], b["synthesis_components"])}
    rows = merged["synthesis_components"]["sst_anomalies"]["bay_of_bengal"]
    assert len(rows) == 2 and rows[0]["event_id"] != rows[1]["event_id"]
    assert select(merged) == marine.component("sst_anomaly", same)
    assert rows[0] == a["synthesis_components"]["sst_anomalies"]["bay_of_bengal"][0]
    changed = sst_reading(monkeypatch, value=3.1)
    assert marine.record_reading(merged, "sst_anomaly", changed) == "retained"
    diagnostics = {}
    assert select(merged, diagnostics=diagnostics) is None
    assert diagnostics == {"component_date_conflict": 1}
    # A separate unconflicted source day can still qualify.
    earlier = sst_reading(monkeypatch, value=2.5, day="2026-06-13")
    marine.record_reading(merged, "sst_anomaly", earlier)
    assert select(merged) == marine.component("sst_anomaly", earlier)
    rows[0]["marine_source"]["reading"]["provenance"]["response_sha256"] = "bad"
    assert a["synthesis_components"]["sst_anomalies"]["bay_of_bengal"][0]["marine_source"]["reading"]["provenance"]["response_sha256"] != "bad"


def test_peak_retains_its_own_source_and_primary_precedes_larger_backup(monkeypatch, tmp_path):
    from src.data import ocean_sst_anomaly as source
    region = next(r for r in source.REGION_REGISTRY if r.slug == "bay_of_bengal")
    path = crw_fixtures.native_file(tmp_path / "invented.nc", region=region, value=4.0)
    native = source._readings_from_noaa_star_netcdf_bytes(
        path.read_bytes(), data_date="2026-06-14", regions=(region,), today=source.datetime.now().date(),
        source_url=f"{source.NOAA_STAR_SSTA_BASE_URL}/2026/ct5km_ssta_v3.1_20260614.nc", retrieved_at=marine.now_utc(),
    )[0]
    s = deepcopy(state.DEFAULT_STATE)
    assert marine.record_reading(s, "sst_anomaly", native) == "retained"
    assert select(s) == marine.component("sst_anomaly", native)
    primary = sst_reading(monkeypatch, value=2.2)
    marine.record_reading(s, "sst_anomaly", primary)
    assert select(s) == marine.component("sst_anomaly", primary)
    peak = sst_reading(monkeypatch, value=3.1, day="2026-06-13")
    marine.record_reading(s, "sst_anomaly", peak)
    assert select(s) == marine.component("sst_anomaly", peak)


def test_point_coral_pair_keeps_grid_scope_and_never_derives_alert(monkeypatch):
    c = coral_point_fixtures.reading()
    s = sst_reading(monkeypatch, slug="great_barrier_reef")
    value = marine.build_bundle(marine.make_payload(marine.component("coral", c), marine.component("sst_anomaly", s), marine.now_utc()))
    assert audit_story_bundle(value).prompt_ready
    facts = {f["label"]: f["value"] for f in value.current_facts}
    assert facts["coral_sample_scope"] == marine.coral_evidence.DHW_POINT_SCOPE
    assert marine.claim_failures("Bleaching Alert Level 2", value)
    assert not marine.claim_failures("NOAA's selected grid point shows 8.3 °C-weeks of heat stress.", value)


@pytest.mark.parametrize("field,value", [
    ("at", "2026-06-15T00:00:00Z"), ("at", "2999-01-01T00:00:00Z"),
    ("event_id", "another-id"), ("marine_source", {}),
])
def test_component_identity_and_dates_refuse_mutation(monkeypatch, field, value):
    s = qualified_state(monkeypatch)
    row = s["synthesis_components"]["sst_anomalies"]["bay_of_bengal"][0]
    row[field] = value
    assert synthesis.detect_marine_compound(s) == []


@pytest.mark.parametrize("field,value", [
    ("anomaly_c", 3.2), ("tier", 1), ("cells_used", 1), ("region_slug", "caribbean"),
    ("date", "2026-06-15"), ("source_leg", "noaa_star_nc"), ("provenance", None),
    ("anomaly_c", float("nan")), ("tier", False),
])
def test_recomputed_identity_does_not_qualify_altered_reading(monkeypatch, field, value):
    reading = replace(sst_reading(monkeypatch), **{field: value})
    s = deepcopy(state.DEFAULT_STATE)
    assert marine.record_reading(s, "sst_anomaly", reading) not in {"retained", "unchanged"}
    assert select(s) is None


@pytest.mark.parametrize("path,value", [
    (("when",), "2026-06-15"), (("event_id",), "other"), (("where",), "Other Ocean"),
    (("headline_metric", "value"), 10), (("current_facts", 3, "value"), "2026-06-16"),
    (("historical_context", "sst_reference_climatology"), {}),
    (("raw_signal_dump", "sst_region_slug"), "caribbean"),
    (("raw_signal_dump", "evaluation_at"), "2026-06-15T12:00:00Z"),
    (("raw_signal_dump", "window_days"), 30), (("raw_signal_dump", "marine_schema_version"), True),
    (("raw_signal_dump", "components", "coral", "marine_source", "reading", "provenance"), {}),
])
def test_projection_mutations_fail_audit_and_direct_checker_before_provider(monkeypatch, path, value):
    source = bundle(monkeypatch)
    obj = source
    for key in path[:-1]:
        obj = getattr(obj, key) if hasattr(obj, "to_dict") else obj[key]
    if hasattr(obj, "to_dict"):
        setattr(obj, path[-1], value)
    else:
        obj[path[-1]] = value
    provider = Mock(side_effect=AssertionError("No paid check for changed evidence"))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    assert not audit_story_bundle(source).prompt_ready
    assert not fact_check.fact_check(FACTUAL, [], source, {}).passed
    provider.assert_not_called()


def test_dynamic_expiry_and_future_acquisition_hold(monkeypatch, marine_clock):
    source = bundle(monkeypatch)
    row = source.raw_signal_dump["components"]["sst_anomaly"]
    # SST window includes day14, expires on day15, even with an old evaluation time.
    marine_clock.current += timedelta(days=12)
    assert marine.validate_component(row, "sst_anomaly", marine.now_utc())
    marine_clock.current += timedelta(days=1)
    with pytest.raises(marine.MarineEvidenceError, match="outside_window"):
        marine.validate_component(row, "sst_anomaly", source.raw_signal_dump["evaluation_at"])
    assert not audit_story_bundle(source).prompt_ready
    marine_clock.current -= timedelta(days=13, seconds=1)
    with pytest.raises(marine.MarineEvidenceError, match="future_acquisition"):
        marine.validate_component(row, "sst_anomaly", marine.now_utc())


def test_future_source_and_evaluation_rejected(monkeypatch, marine_clock):
    reading = sst_reading(monkeypatch)
    row = marine.component("sst_anomaly", reading)
    with pytest.raises(marine.MarineEvidenceError, match="future_evaluation"):
        marine.validate_component(row, "sst_anomaly", "2999-01-01T00:00:00Z")
    marine_clock.current -= timedelta(days=3)
    with pytest.raises(marine.MarineEvidenceError, match="outside_window"):
        marine.validate_component(row, "sst_anomaly", marine.now_utc())


def test_capacity_oversize_and_malformed_regions_do_not_certify_partial_pool(monkeypatch):
    s = qualified_state(monkeypatch)
    original = select(s)
    s["synthesis_components"]["sst_anomalies"]["bay_of_bengal"] = [deepcopy(original)] * marine.COMPONENT_LIMIT
    diagnostics = {}
    assert select(s, diagnostics=diagnostics) is None and diagnostics["component_capacity"] == 1
    assert marine.record_reading(s, "sst_anomaly", sst_reading(monkeypatch, value=3)) == "component_capacity"
    s["synthesis_components"]["sst_anomalies"]["bay_of_bengal"] = [original]
    s["synthesis_components"]["corals"]["gbr_northern"] = "malformed"
    assert len(synthesis.detect_marine_compound(s)) == 1
    oversized = sst_reading(monkeypatch)
    oversized.provenance["extra"] = "x" * marine.COMPONENT_BYTES
    assert marine.record_reading(s, "sst_anomaly", oversized) == "component_too_large"


def test_legacy_source_is_withheld_before_writer(monkeypatch):
    from tests.test_synthesis import _state_with_marine_components
    assert synthesis.detect_marine_compound(_state_with_marine_components()) == []
    old = build_synthesis_bundle({"kind": "marine_compound", "region": "Great Nicobar", "event_id": "legacy", "components": []})
    write = Mock(side_effect=AssertionError("No writer for legacy evidence"))
    monkeypatch.setattr(pipeline.writer, "write_tweet", write)
    assert pipeline.generate_draft(old, _state_with_memory()) is None
    write.assert_not_called()


@pytest.mark.parametrize("text", [CAUSAL, "Both products show the same waters overheating.",
    "The readings overlap.", "They were measured at the same time.", "Corals are dying.",
    "Mass bleaching is expected.", "A marine heatwave hit the reef.", "Both values were measured on the same day."])
def test_unsupported_relation_before_direct_paid_checks(monkeypatch, text):
    source = bundle(monkeypatch)
    provider = Mock(side_effect=AssertionError("No provider for unwarranted relationship"))
    monkeypatch.setattr(fact_check, "_call_gemini", provider)
    assert marine.claim_failures(text, source)
    assert not fact_check.fact_check(text, [], source, {}).passed
    provider.assert_not_called()


def test_regional_alert_needs_the_real_seven_day_maximum_qualifier(monkeypatch):
    source = bundle(monkeypatch)
    assert marine.claim_failures("Bleaching Alert Level 1 today.", source)
    assert not marine.claim_failures("NOAA's 7-day maximum was Bleaching Alert Level 1.", source)


@pytest.mark.usefixtures("configured_pipeline_providers")
@pytest.mark.parametrize("text", [FACTUAL, CAUSAL])
def test_pipeline_and_retained_checks_keep_exact_evidence_and_required_models(monkeypatch, text):
    source = bundle(monkeypatch)
    before = deepcopy(source.to_dict())
    candidate = WriterResult(text, None, "number", None, None, "Invented fixture")
    monkeypatch.setattr(pipeline.writer, "write_tweet", Mock(return_value=candidate))
    calls = []
    monkeypatch.setattr(pipeline, "run_safety_pipeline", lambda t: (calls.append("safety") or (True, None)))
    monkeypatch.setattr(fact_check, "fact_check", lambda *args: (calls.append("fact") or FactCheckResult(True, [], "Offline fixture")))
    monkeypatch.setattr(pipeline.critic, "critic_review", lambda *args, **kw: (calls.append("critic") or CriticResult(True, None, "Offline fixture")))
    result = pipeline.generate_draft(source, _state_with_memory())
    assert bool(result) == (text == FACTUAL)
    assert calls == (["safety", "fact", "critic"] if text == FACTUAL else [])
    saved = packet(dict(candidate=asdict(candidate), candidate_id="c" * 64, bundle=before, policy=current_editorial_policy()))
    retained = deepcopy(saved)
    assert check_requests.deterministic_result(saved)["passed"] == (text == FACTUAL), check_requests.deterministic_result(saved)
    assert saved == retained and source.to_dict() == before


def test_scalar_related_projection_excludes_marine_even_with_country():
    from src.two_bot.multisignal import attach_related_signals
    from tests.test_multisignal import _cand
    q = [_cand(event_id="marine", signal_kind=marine.SIGNAL_KIND, country="IN"), _cand(event_id="other", country="IN")]
    attach_related_signals(q)
    assert not q[0].bundle.related_signals and not q[1].bundle.related_signals


def test_qualification_sources_all_bound_in_policy():
    files = source_manifest()["files"]
    for name in ("src/editorial/marine_evidence.py", "src/editorial/synthesis.py", "src/orchestrator/sources/synthesis.py",
                 "src/orchestrator/sources/coral_dhw.py", "src/orchestrator/sources/ocean_sst_anomaly.py"):
        assert name in files


def test_real_source_runners_record_before_individual_caps_and_queue_exact_pair(monkeypatch):
    from src.data import ocean_sst_anomaly as source
    from src.orchestrator.sources import ocean_sst_anomaly as sr, coral_dhw as cr, synthesis as runner
    from tests import coral_regional_fixtures as cf
    region = next(r for r in source.REGION_REGISTRY if r.slug == "bay_of_bengal")
    by_url = {source._build_url(r): r for r in source.REGION_REGISTRY}
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return crw_fixtures.response(crw_fixtures.metadata_body() if url == source.contract.METADATA_URL
            else crw_fixtures.csv_body(by_url[url], value=2.2 if by_url[url].slug == region.slug else 0))
    monkeypatch.setattr(source, "fetch_with_retry", get)
    s, run = deepcopy(state.DEFAULT_STATE), {"sources": []}
    sr.run_ocean_sst_anomaly(s, run)
    assert len(calls) == 14  # Existing one-metadata +13-region collection; no extra source calls.
    assert run["sources"][-1]["details"]["marine_components"] == {"retained": 1}
    assert not s.get("_triage_queue")  # Quiet individual SST still has complete marine source.
    p = cf.packet(region_id="great_nicobar", name="Great Nicobar")
    cf.install_transport(monkeypatch, p)
    monkeypatch.setattr(cr, "_coral_dhw_annual_cap_reached", lambda *_: True)
    cr.run_coral_dhw(s, run)
    assert run["sources"][-1]["details"]["marine_components"] == {"retained": 1}
    assert not s.get("_triage_queue") and not s["coral_dhw_last_tier"]
    monkeypatch.setattr(runner, "_should_draft", lambda *_: True)
    runner.run_synthesis(s, run)
    assert run["sources"][-1]["status"] == "success"
    queue = s["_triage_queue"]
    assert len(queue) == 1
    candidate = queue[0]
    assert audit_story_bundle(candidate.bundle).prompt_ready
    assert candidate.bundle.raw_signal_dump["components"]["sst_anomaly"] == select(s)
    assert candidate.bundle.raw_signal_dump["components"]["coral"] == select(s, "coral", "great_nicobar")
    assert not s.get("synthesis_cooldown", {}).get(synthesis.RULE_MARINE_COMPOUND)
    candidate.on_draft_success()
    assert s["synthesis_cooldown"][synthesis.RULE_MARINE_COMPOUND]["great_nicobar"]


def test_current_source_rules_remain_stricter_than_comparison_window(monkeypatch, marine_clock):
    source = bundle(monkeypatch)
    marine_clock.current += timedelta(days=5)
    # The primary regional coral source expires after five days; the14-day
    # comparison window is an upper bound, not an exception to source freshness.
    assert marine.bundle_failures(source)
    assert not audit_story_bundle(source).prompt_ready


def test_point_and_regional_coral_are_not_ranked_as_one_statistic():
    point = coral_point_fixtures.reading(12)
    regional = marine_fixtures.coral_regional_fixtures.reading(
        8.25, region_id="gbr_northern", name="Invented regional reef")
    s = deepcopy(state.DEFAULT_STATE)
    assert marine.record_reading(s, "coral", point) == "retained"
    assert marine.record_reading(s, "coral", regional) == "retained"
    assert select(s, "coral", "gbr_northern") == marine.component("coral", regional)


from tests import test_check_executor as execution
store, inputs = execution.store, execution.inputs


@pytest.mark.usefixtures("configured_pipeline_providers")
def test_real_retained_executor_withholds_before_paid_stages(store, inputs, monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    source = bundle(monkeypatch)
    inputs.update(bundle=source, bundle_sha256=fingerprint(source.to_dict()), policy=current_editorial_policy())
    pair, grant = execution.batches.started(store, inputs)
    rows = execution.batches.rows(pair)
    candidate = json.loads(rows[0]["result"]["message"]["content"][0]["text"])
    candidate["tweet"] = CAUSAL
    rows[0]["result"]["message"]["content"][0]["text"] = json.dumps(candidate)
    receipt = execution.batches.retain(store, grant, execution.batches.contract.raw_rows(rows))
    payload = dict(job_id=pair[1]["job_id"], owner="worker-one", fence=1,
        receipt_id=receipt["receipt_id"], current_context=execution.batches.contract.context(pair[0]),
        custom_id=json.loads(pair[0])["requests"][0]["custom_id"], bundle=source.to_dict(),
        memory=inputs["memory"].to_dict(), checker_state=deepcopy(store.read()[1]))
    check_set = store.candidate_checks("intake", payload, now=execution.NOW)
    case = dict(store=store, identity=check_set["check_set_id"], payload=payload)
    sent, _ = execution.provider(monkeypatch, [])
    before = deepcopy(store.read())
    result = execution.run(case)
    assert not result["required_checks_completed"] and not sent
    assert result["checks"]["stages"]["deterministic"] == "rejected"
    assert not execution.run(case)["required_checks_completed"] and not sent
    assert store.read() == before
    assert execution.saved(case)["packet"]["bundle"] == source.to_dict()


def test_shared_dashboard_fixture_is_exact_real_parser_output(monkeypatch):
    from pathlib import Path
    shared = json.loads((Path(__file__).parent / "fixtures/marine-components.json").read_text())
    assert qualified_state(monkeypatch)["synthesis_components"] == shared
