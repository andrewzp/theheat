"""Offline strict two-angle contracts; ordinary requests keep their exact bytes."""

from copy import deepcopy
import hashlib
import json

import pytest

from src.editorial.revisions import fingerprint
from src.two_bot import batch_contract as batch, important_variants as important, writer
from tests.two_bot.test_batch_contract import inputs as inputs, result, raw_rows, context


def allowance(inputs):
    bundle = inputs["bundle"]
    # Actual retained fact, not an editorial output or a preexisting check.
    bundle.current_facts.append(
        dict(label="Synthetic daily detections", value=7, unit="detections")
    )
    policy = inputs["policy"]
    policy["flags"]["critic_revise_enabled"] = False
    return dict(
        schema_version=1,
        kind=important.KIND,
        basis="invented_local_allowance",
        brief_id="b" * 64,
        brief_sha256="b" * 64,
        context=dict(
            bundle_sha256=fingerprint(bundle.to_dict()),
            memory_sha256=fingerprint(inputs["memory"].to_dict()),
            policy_sha256=fingerprint(policy),
            publication_epoch=inputs["publication_epoch"],
        ),
        authorized_subject="fixture-editor",
        authentication_context="fixture-local",
        importance_reason="Invented important event",
        valid_from=inputs["created_at"],
        valid_until=inputs["useful_until"],
        angles=[
            dict(slot=1, kind="headline_first", fact_sha256=fingerprint(bundle.headline_metric)),
            dict(
                slot=2,
                kind="context_first",
                index=len(bundle.current_facts) - 1,
                fact_sha256=fingerprint(bundle.current_facts[-1]),
            ),
        ],
        preferred_slot=1,
        max_writer_items=2,
        max_submit_attempts=1,
        max_collection_cycles=4,
        max_candidate_provider_checks=6,
        max_rewrites=0,
        writer_reservation=dict(
            estimate_sha256="e" * 64,
            reserve_micro_usd=20,
            provider="anthropic",
            model=policy["models"]["writer"],
            role="writer",
        ),
        check_reservations={
            stage: dict(
                estimate_sha256="e" * 64,
                reserve_micro_usd=5,
                provider="google",
                model=policy["models"][stage],
                role=stage,
            )
            for stage in ("safety", "fact_check", "critic")
        },
        max_group_commitment_micro_usd=50,
    )


def plan(inputs):
    value = allowance(inputs)
    return important.prepare_plan(
        inputs["bundle"],
        inputs["memory"],
        policy=inputs["policy"],
        allowance=value,
        job_id="iv_" + "a" * 64,
        created_at=inputs["created_at"],
        useful_until=inputs["useful_until"],
    )


def test_two_angle_plan_is_exact_and_allowance_bound(inputs):
    raw = plan(inputs)
    value = json.loads(raw)
    verified = batch.validated_batch_plan(raw, expected_plan_sha256=hashlib.sha256(raw).hexdigest())
    assert verified == value and len(value["requests"]) == 2
    assert value["policy"]["flags"]["writer_samples"] == 1
    first, second = [r["params"] for r in value["requests"]]
    assert first != second and first["system"] == second["system"]
    assert first["model"] == second["model"] == inputs["policy"]["models"]["writer"]
    assert first["output_config"] == second["output_config"]
    assert "Revision context" not in first["messages"][0]["content"]
    for mutate in (
        lambda v: v["allowance"].__setitem__("max_writer_items", 3),
        lambda v: v["policy"]["flags"].__setitem__("writer_samples", 2),
        lambda v: v["requests"][0]["params"].__setitem__("model", "other"),
        lambda v: v["allowance"]["angles"][1].__setitem__("index", 99),
    ):
        bad = deepcopy(value)
        mutate(bad)
        encoded = important.canonical(bad)
        with pytest.raises(batch.BatchContractError):
            batch.validated_batch_plan(
                encoded, expected_plan_sha256=hashlib.sha256(encoded).hexdigest()
            )


def test_partial_member_does_not_discard_identified_sibling(inputs):
    raw = plan(inputs)
    first = result(raw, 0)
    kwargs = dict(
        expected_plan_sha256=hashlib.sha256(raw).hexdigest(),
        current_context=context(raw),
        now="2026-09-29T13:00:00Z",
    )
    partial = batch.collect_batch_results(raw, raw_rows([first]), **kwargs)
    assert partial["rows"][0]["eligible_for_checks"] and partial["complete"] is False
    malformed = dict(
        custom_id=json.loads(raw)["requests"][1]["custom_id"],
        result={"type": "succeeded", "message": None},
    )
    report = batch.collect_batch_results(raw, raw_rows([first, malformed]), **kwargs)
    assert report["rows"][0]["eligible_for_checks"] and not report["rows"][1]["eligible_for_checks"]
    assert report["rows"][1]["blocked_reasons"] == ["invalid_member_content"]
    for rows in ([first, first], [first, dict(malformed, custom_id="unknown")]):
        with pytest.raises(batch.BatchContractError):
            batch.collect_batch_results(raw, raw_rows(rows), **kwargs)


def test_routine_bytes_remain_shared_request(inputs):
    before = batch.prepare_batch_plan(**inputs)
    assert json.loads(before)["requests"][0]["params"] == writer.anthropic_writer_request(
        writer.build_writer_user_prompt(inputs["bundle"], inputs["memory"])
    )
    assert before == batch.prepare_batch_plan(**inputs)


@pytest.mark.parametrize("anchor", ["headline", "context"])
@pytest.mark.parametrize("field", ["label", "unit"])
@pytest.mark.parametrize("blank", ["", " \t\n"])
def test_angle_fact_rejects_blank_label_or_unit_with_matching_identity(
    inputs, anchor, field, blank
):
    value = allowance(inputs)
    bundle = inputs["bundle"]
    important.angle_facts(bundle, value)
    index = 0 if anchor == "headline" else 1
    fact = bundle.headline_metric if anchor == "headline" else bundle.current_facts[-1]
    fact[field] = blank
    value["angles"][index]["fact_sha256"] = fingerprint(fact)
    value["context"]["bundle_sha256"] = fingerprint(bundle.to_dict())
    before = deepcopy(bundle.to_dict())
    with pytest.raises(important.ImportantContractError, match="important_angle_fact_invalid"):
        important.angle_facts(bundle, value)
    assert bundle.to_dict() == before


@pytest.mark.parametrize(
    "change",
    [
        "missing_unit",
        "same_fact",
        "missing_index",
        "samples",
        "revise",
        "provider",
        "model",
        "amount",
        "prompt",
        "expired",
    ],
)
def test_allowance_cannot_widen_or_replace_real_writer_inputs(inputs, change):
    value = allowance(inputs)
    policy = inputs["policy"]
    if change == "missing_unit":
        inputs["bundle"].current_facts[-1].pop("unit")
    elif change == "same_fact":
        inputs["bundle"].current_facts[-1] = deepcopy(inputs["bundle"].headline_metric)
        value["angles"][1]["fact_sha256"] = value["angles"][0]["fact_sha256"]
    elif change == "missing_index":
        value["angles"][1]["index"] = 99
    elif change == "samples":
        policy["flags"]["writer_samples"] = 3
    elif change == "revise":
        policy["flags"]["critic_revise_enabled"] = True
    elif change in {"provider", "model", "amount"}:
        key = "reserve_micro_usd" if change == "amount" else change
        value["writer_reservation"][key] = 21 if change == "amount" else "other"
    elif change == "prompt":
        value["prompt"] = "Unbound replacement text"
    elif change == "expired":
        value["valid_until"] = value["valid_from"]
    with pytest.raises(important.ImportantContractError):
        important.prepare_plan(
            inputs["bundle"],
            inputs["memory"],
            policy=policy,
            allowance=value,
            job_id="iv_" + "a" * 64,
            created_at=inputs["created_at"],
            useful_until=inputs["useful_until"],
        )


def test_retained_plan_reads_do_not_rebind_to_todays_writer_prompt(inputs, monkeypatch):
    raw = plan(inputs)
    monkeypatch.setattr(writer, "build_writer_user_prompt", lambda *args: "Changed current prompt")
    assert (
        batch.validated_batch_plan(raw, expected_plan_sha256=hashlib.sha256(raw).hexdigest())[
            "schema_version"
        ]
        == 2
    )
    original = json.loads(raw)
    changed = important.prepare_plan(
        inputs["bundle"],
        inputs["memory"],
        policy=inputs["policy"],
        allowance=original["allowance"],
        job_id=original["job_id"],
        created_at=inputs["created_at"],
        useful_until=inputs["useful_until"],
    )
    assert changed != raw


def aqi_inputs(inputs):
    from tests.air_quality_fixtures import observation
    from src.data.air_quality import detect_pm25_hazard
    from src.two_bot.intern.air_quality import build_pm25_hazard_bundle

    value = allowance(inputs)
    bundle = build_pm25_hazard_bundle(detect_pm25_hazard(observation(pm25=172, us_aqi=210)))
    inputs["bundle"] = bundle
    inputs["bundle_sha256"] = fingerprint(bundle.to_dict())
    value["context"]["bundle_sha256"] = inputs["bundle_sha256"]
    fact = next(f for f in bundle.current_facts if f["label"] == "us_aqi_daily_max")
    value["angles"] = [
        dict(slot=1, kind="headline_first", fact_sha256=fingerprint(bundle.headline_metric)),
        dict(
            slot=2,
            kind="context_first",
            index=bundle.current_facts.index(fact),
            fact_sha256=fingerprint(fact),
        ),
    ]
    return value, fact


def important_plan(inputs, value):
    return important.prepare_plan(
        inputs["bundle"],
        inputs["memory"],
        policy=inputs["policy"],
        allowance=value,
        job_id="iv_" + "a" * 64,
        created_at=inputs["created_at"],
        useful_until=inputs["useful_until"],
    )


def test_typed_aqi_anchor_preserves_ordinary_bundle_prompt_and_plan(inputs, monkeypatch):
    value, fact = aqi_inputs(inputs)
    bundle_before, fact_before = deepcopy(inputs["bundle"].to_dict()), deepcopy(fact)
    prompt = writer.build_writer_user_prompt(inputs["bundle"], inputs["memory"])
    ordinary = batch.prepare_batch_plan(**inputs)
    raw = important_plan(inputs, value)
    body = json.loads(raw)
    second = body["requests"][1]["params"]["messages"][0]["content"]
    assert '"unit":"US AQI"' in second and "not a station observation" in second
    assert "Exact model, run and resolution are unknown" in second
    assert (
        inputs["bundle"].to_dict() == bundle_before and fact == fact_before and "unit" not in fact
    )
    assert writer.build_writer_user_prompt(inputs["bundle"], inputs["memory"]) == prompt
    assert batch.prepare_batch_plan(**inputs) == ordinary

    # Passive historical reads retain exact identities without rerunning science
    # or today's prompt/model, even after those implementations change.
    def forbidden(*args, **kwargs):
        pytest.fail("Historical plan attempted current science/prompt work")

    from src.data import air_quality_contract, air_quality_evidence

    with monkeypatch.context() as patch:
        patch.setattr(important, "audit_story_bundle", forbidden)
        patch.setattr(air_quality_contract, "validate_window", forbidden)
        patch.setattr(air_quality_evidence, "validate_bundle", forbidden)
        patch.setattr(writer, "build_writer_user_prompt", forbidden)
        assert (
            batch.validated_batch_plan(raw, expected_plan_sha256=hashlib.sha256(raw).hexdigest())
            == body
        )


@pytest.mark.parametrize(
    "change",
    [
        "null",
        "bool",
        "string",
        "duplicate",
        "wrong_kind",
        "wrong_label",
        "wrong_index",
        "fact_hash",
        "value",
        "missing_series",
        "null_series",
        "incomplete",
        "invalid_sample",
        "unit",
        "missing_unit",
        "date",
        "city",
        "source",
        "aggregate",
        "appended_alias",
    ],
)
def test_typed_aqi_refuses_unsupported_or_changed_source_before_writer(inputs, monkeypatch, change):
    value, fact = aqi_inputs(inputs)
    bundle = inputs["bundle"]
    window = bundle.raw_signal_dump["forecast_window"]
    if change in {"null", "bool", "string", "value"}:
        fact["value"] = {"null": None, "bool": True, "string": "210", "value": 211}[change]
    elif change == "duplicate":
        bundle.current_facts.append(deepcopy(fact))
    elif change == "wrong_kind":
        bundle.signal_kind = "fire"
    elif change == "wrong_label":
        fact["label"] = "another_index"
    elif change == "wrong_index":
        value["angles"][1]["index"] = 0
    elif change == "fact_hash":
        value["angles"][1]["fact_sha256"] = "f" * 64
    elif change == "missing_series":
        window["series"].pop("us_aqi")
    elif change == "null_series":
        window["series"]["us_aqi"]["values"] = None
    elif change == "incomplete":
        window["series"]["us_aqi"]["values"] = [210] * 23
    elif change == "invalid_sample":
        window["series"]["us_aqi"]["values"][0] = True
    elif change == "unit":
        window["series"]["us_aqi"]["unit"] = "European AQI"
    elif change == "missing_unit":
        window["series"]["us_aqi"].pop("unit")
    elif change == "date":
        window["date"] = "2026-06-09"
    elif change == "city":
        window["requested_location"]["city"] = "Other city"
    elif change == "source":
        window["source_product"] = "another-model"
    elif change == "aggregate":
        window["series"]["us_aqi"]["values"] = [211] * 24
    else:
        bundle.current_facts.append(
            dict(label="retained_who_24h_guideline", value=15, unit="μg/m³")
        )
    if change != "fact_hash":
        value["angles"][1]["fact_sha256"] = fingerprint(fact)
    value["context"]["bundle_sha256"] = fingerprint(bundle.to_dict())

    def forbidden(*args, **kwargs):
        pytest.fail("Unqualified AQI reached writer request construction")

    monkeypatch.setattr(writer, "anthropic_writer_request", forbidden)
    with pytest.raises(important.ImportantContractError):
        important_plan(inputs, value)
