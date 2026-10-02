"""Synthetic immutable output/formatting contracts; no provider or source claim."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint, text_hash
from src.two_bot import candidate_derivation as derivation, check_requests
from src.two_bot.source_links import format_source_link
from src.two_bot.types import WriterResult
from tests.two_bot.source_link_fixtures import bundle, TEXT, URL
from tests.two_bot.conftest import _memory


@pytest.fixture
def inputs():
    return dict(candidate=asdict(WriterResult(
        tweet=TEXT + " nhc.noaa.gov/text/SYN…", kill_reason=None,
        angle_chosen="synthetic", era_anchor_used=None, peer_comparison_used=None,
        reasoning="Invented fixture, not a weather report.",
    )), candidate_id="c" * 64, bundle=bundle().to_dict(), policy=current_editorial_policy())


def packet(inputs):
    value = derivation.derive_candidate(**inputs)
    state = {"drafts": []}
    return dict(inputs, schema_version=2, derivation=value, derivation_id=fingerprint(value),
                text_sha256=value["text_sha256"], memory=_memory().to_dict(),
                checker_state=state, checker_state_sha256=fingerprint(state), check_date="2026-01-01")


def test_final_content_is_separate_from_raw_metadata_and_never_mutates_inputs(inputs):
    original = deepcopy(inputs)
    saved = packet(inputs)
    assert saved["candidate"]["tweet"].endswith("SYN…")
    assert derivation.checked_text(saved) == TEXT + "\n" + URL
    assert saved["derivation"]["raw_candidate_id"] == inputs["candidate_id"]
    assert saved["derivation"]["raw_candidate_sha256"] == fingerprint(inputs["candidate"])
    assert saved["text_sha256"] != text_hash(saved["candidate"]["tweet"])
    assert inputs == original and packet(inputs) == saved


@pytest.mark.parametrize("values,kind,text", [
    ([URL], "cyclone_tier_crossing", TEXT),
    ([URL], "cyclone_tier_crossing", TEXT + "\n" + URL),
    ([URL], "fire", TEXT),
    ([{}], "cyclone_tier_crossing", TEXT),
    ([URL, "https://example.invalid/source"], "cyclone_tier_crossing", TEXT),
    ([URL], "cyclone_tier_crossing", TEXT + " uncertain…"),
    ([URL], "cyclone_tier_crossing", "A" * 270),
], ids=["append", "exact", "noncyclone", "malformed", "conflict", "uncertain", "too-long"])
def test_uses_actual_synchronous_formatter_without_extra_rules(inputs, values, kind, text):
    source = bundle(values, kind)
    inputs.update(bundle=source.to_dict())
    inputs["candidate"]["tweet"] = text
    assert derivation.checked_text(packet(inputs)) == format_source_link(text, source)


@pytest.mark.parametrize("field", ["raw_candidate_id", "raw_candidate_sha256", "bundle_sha256",
                                  "policy_sha256", "text_sha256"])
def test_changed_binding_is_never_treated_as_historical_unavailability(inputs, field):
    saved = packet(inputs)
    saved["derivation"][field] = "f" * 64
    saved["derivation_id"] = fingerprint(saved["derivation"])
    with pytest.raises(ValueError, match="changed_derivation_binding"):
        derivation.checked_text(saved)


def test_consistent_fabricated_final_hashes_do_not_prove_the_transformation(inputs):
    saved = packet(inputs)
    saved["derivation"]["final_text"] = "Different invented text."
    saved["derivation"]["text_sha256"] = text_hash(saved["derivation"]["final_text"])
    saved["text_sha256"] = saved["derivation"]["text_sha256"]
    saved["derivation_id"] = fingerprint(saved["derivation"])
    with pytest.raises(ValueError, match="changed_derived_text"):
        derivation.checked_text(saved)


def test_deterministic_observation_cannot_pass_for_an_invalid_packet(inputs):
    saved = packet(inputs)
    saved["derivation"]["final_text"] = "Changed text."
    result = check_requests.interpret_observation(saved, "deterministic", {"complete": True},
        b'{"passed":true,"failures":[],"failure_count":0}')
    assert result["execution_status"] == "error" and result["verdict"] is None


@pytest.mark.parametrize("version", [True, 1.0, 2, None])
def test_derivation_schema_is_an_exact_supported_integer(inputs, version):
    saved = packet(inputs)
    saved["derivation"]["schema_version"] = version
    with pytest.raises(ValueError, match="invalid_derivation_schema"):
        derivation.checked_text(saved)


@pytest.mark.parametrize("change", ["source", "version", "name", "unreadable"])
def test_different_trusted_implementation_is_explicitly_unavailable(inputs, monkeypatch, change):
    saved = packet(inputs)
    current = derivation.formatter_identity()
    if change == "source":
        current["source_sha256"] = "f" * 64
    elif change == "version":
        current["version"] = 2
    elif change == "name":
        current["name"] = "different-trusted-formatter"
    if change == "unreadable":
        monkeypatch.setattr(derivation, "formatter_identity", lambda: (_ for _ in ()).throw(OSError()))
    else:
        monkeypatch.setattr(derivation, "formatter_identity", lambda: current)
    monkeypatch.setattr(derivation, "format_source_link", lambda *a: pytest.fail("Historical reformat"))
    assert derivation.packet_verification(saved) == "formatter_unavailable"
    with pytest.raises(ValueError, match="formatter_unavailable"):
        derivation.checked_text(saved)


def test_self_supplied_implementation_hash_cannot_select_trusted_code(inputs):
    inputs["policy"]["source_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="formatter_unavailable"):
        derivation.derive_candidate(**inputs)


def test_old_packet_remains_raw_history_without_implicit_current_text(inputs):
    saved = dict(inputs, schema_version=1, text_sha256=text_hash(inputs["candidate"]["tweet"]))
    assert derivation.packet_verification(saved) == "legacy_check_packet"
    with pytest.raises(ValueError, match="legacy_check_packet"):
        derivation.checked_text(saved)
    saved["derivation"] = {}
    with pytest.raises(ValueError, match="invalid_legacy"):
        derivation.packet_verification(saved)


@pytest.mark.parametrize("version", [True, 2.0, 3, None])
def test_packet_version_cannot_silently_fall_back_to_raw_text(inputs, version):
    saved = packet(inputs)
    saved["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported_check_packet"):
        derivation.checked_text(saved)


@pytest.mark.parametrize("field", ["derivation_id", "text_sha256"])
def test_packet_must_bind_the_exact_derivation_identity(inputs, field):
    saved = packet(inputs)
    saved[field] = "f" * 64
    with pytest.raises(ValueError, match="changed_derivation_identity"):
        derivation.checked_text(saved)


@pytest.mark.parametrize("field", ["candidate", "bundle", "policy"])
def test_changed_raw_input_does_not_inherit_a_formatted_text(inputs, field):
    saved = packet(inputs)
    if field == "candidate":
        saved[field]["reasoning"] = "Changed raw metadata."
    elif field == "bundle":
        saved[field]["where"] = "Different place"
    else:
        saved[field]["models"]["writer"] = "changed-model"
    with pytest.raises(ValueError, match="changed_derivation_binding"):
        derivation.checked_text(saved)


@pytest.mark.parametrize("field", ["candidate", "bundle"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "\ud800", b"bytes"])
def test_invalid_json_never_reaches_the_formatter(inputs, monkeypatch, field, bad):
    inputs[field]["reasoning" if field == "candidate" else "where"] = bad
    monkeypatch.setattr(derivation, "format_source_link", lambda *a: pytest.fail("Invalid JSON formatted"))
    with pytest.raises(ValueError):
        derivation.derive_candidate(**inputs)


def test_missing_candidate_defaults_and_constructor_repair_are_refused(inputs):
    bad = deepcopy(inputs)
    del bad["candidate"]["initial_response"]
    with pytest.raises(ValueError, match="invalid_derivation_candidate"):
        derivation.derive_candidate(**bad)
    bad = deepcopy(inputs)
    del bad["bundle"]["historical_context"]
    with pytest.raises(ValueError, match="roundtrip_changed"):
        derivation.derive_candidate(**bad)


def test_candidate_and_derivation_size_limits(inputs, monkeypatch):
    monkeypatch.setattr(derivation, "MAX_INPUT_BYTES", 100)
    with pytest.raises(ValueError, match="too_large"):
        derivation.derive_candidate(**inputs)
    monkeypatch.setattr(derivation, "MAX_INPUT_BYTES", 2_000_000)
    monkeypatch.setattr(derivation, "MAX_DERIVATION_BYTES", 100)
    with pytest.raises(ValueError, match="too_large"):
        derivation.derive_candidate(**inputs)


def test_constructor_failure_does_not_echo_untrusted_keys(inputs):
    inputs["bundle"]["untrusted-private-fixture-key"] = "value"
    with pytest.raises(ValueError) as error:
        derivation.derive_candidate(**inputs)
    assert str(error.value) == "invalid_derivation_bundle"


@pytest.mark.parametrize("stage", ["deterministic", "safety", "fact_check", "critic"])
def test_each_actual_request_uses_final_text(inputs, stage):
    saved = packet(inputs)
    request = check_requests.prepare_request(saved, stage)
    if stage == "deterministic":
        assert request["check_set_sha256"] == fingerprint(saved)
    else:
        import json
        encoded = json.dumps(request, ensure_ascii=False)
        assert URL in encoded and "SYN…" not in encoded


def test_local_checks_and_response_interpretation_receive_final_text(inputs, monkeypatch):
    saved = packet(inputs)
    seen = []
    original = check_requests.fact_check.local_rejection
    def local(tweet, *args):
        seen.append(tweet)
        return original(tweet, *args)
    monkeypatch.setattr(check_requests.fact_check, "local_rejection", local)
    check_requests.deterministic_result(saved)
    assert seen == [TEXT + "\n" + URL]
    from tests.test_check_executor import envelope
    from src.two_bot.types import FactCheckResult
    def interpreted(tweet, *args):
        seen.append(tweet)
        return FactCheckResult(passed=False, raw_response="{}", extracted_claims=[], failures=["fixture rejection"])
    monkeypatch.setattr(check_requests.fact_check, "interpret_response", interpreted)
    result = check_requests.interpret_observation(saved, "fact_check", {"complete": True, "http_status": 200}, envelope("{}"))
    assert result["verdict"] == "reject" and seen == [TEXT + "\n" + URL] * 2
