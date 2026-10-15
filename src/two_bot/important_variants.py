"""Strict local two-angle allowance and versioned writer requests; no transport."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from src.commands.schema import utc_datetime, utc_text
from src.editorial.policy import valid_policy
from src.editorial.revisions import fingerprint
from src.two_bot import writer
from src.two_bot.candidate_derivation import retained_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.types import MemorySlice

KIND = "important_event_two_angles_v1"
MAX_ALLOWANCE = 16384
CONTEXT = {"bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch"}
FIELDS = {
    "schema_version",
    "kind",
    "basis",
    "brief_id",
    "brief_sha256",
    "context",
    "authorized_subject",
    "authentication_context",
    "importance_reason",
    "valid_from",
    "valid_until",
    "angles",
    "preferred_slot",
    "max_writer_items",
    "max_submit_attempts",
    "max_collection_cycles",
    "max_candidate_provider_checks",
    "max_rewrites",
    "writer_reservation",
    "check_reservations",
    "max_group_commitment_micro_usd",
}
PLAN_FIELDS = {
    "schema_version",
    "kind",
    "job_id",
    "publication_epoch",
    "created_at",
    "useful_until",
    "minimum_window_seconds",
    "samples",
    "experiment_id",
    "bundle_sha256",
    "memory_sha256",
    "policy",
    "policy_sha256",
    "params_sha256",
    "allowance",
    "allowance_sha256",
    "bundle",
    "memory",
    "requests",
}
SHA = re.compile(r"[0-9a-f]{64}")


class ImportantContractError(ValueError):
    """Deterministic bounded refusal, distinct from storage/program failures."""


def require(ok, code):
    if not ok:
        raise ImportantContractError(code)


def canonical(value):
    fingerprint(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _sha(value):
    require(
        isinstance(value, str) and SHA.fullmatch(value) is not None, "important_identity_invalid"
    )


def _fact(value):
    require(
        isinstance(value, dict) and all(k in value for k in ("label", "value", "unit")),
        "important_angle_fact_missing",
    )
    require(
        isinstance(value["label"], str)
        and bool(value["label"].strip())
        and isinstance(value["unit"], str)
        and bool(value["unit"].strip())
        and type(value["value"]) in (str, int, float)
        and value["value"] != "",
        "important_angle_fact_invalid",
    )
    canonical(value)


def allowance_document(value):
    require(
        isinstance(value, dict) and set(value) == FIELDS and len(canonical(value)) <= MAX_ALLOWANCE,
        "important_allowance_invalid",
    )
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["kind"] == KIND
        and value["basis"] == "invented_local_allowance",
        "important_allowance_invalid",
    )
    for key in ("brief_id", "brief_sha256"):
        _sha(value[key])
    require(value["brief_id"] == value["brief_sha256"], "important_brief_changed")
    context = value["context"]
    require(isinstance(context, dict) and set(context) == CONTEXT, "important_context_invalid")
    for key in CONTEXT - {"publication_epoch"}:
        _sha(context[key])
    require(
        isinstance(context["publication_epoch"], str)
        and 0 < len(context["publication_epoch"]) <= 128,
        "important_context_invalid",
    )
    for key, limit in (
        ("authorized_subject", 200),
        ("authentication_context", 200),
        ("importance_reason", 500),
    ):
        require(
            isinstance(value[key], str) and 0 < len(value[key].strip()) <= limit,
            "important_nomination_invalid",
        )
    start, end = utc_datetime(value["valid_from"]), utc_datetime(value["valid_until"])
    require(
        utc_text(start) == value["valid_from"]
        and utc_text(end) == value["valid_until"]
        and 3600 < (end - start).total_seconds() <= 86400,
        "important_window_invalid",
    )
    for key, expected in (
        ("preferred_slot", 1),
        ("max_writer_items", 2),
        ("max_submit_attempts", 1),
        ("max_collection_cycles", 4),
        ("max_candidate_provider_checks", 6),
        ("max_rewrites", 0),
    ):
        require(type(value[key]) is int and value[key] == expected, "important_limit_invalid")
    angles = value["angles"]
    require(isinstance(angles, list) and len(angles) == 2, "important_angles_invalid")
    require(
        isinstance(angles[0], dict)
        and set(angles[0]) == {"slot", "kind", "fact_sha256"}
        and type(angles[0]["slot"]) is int
        and angles[0]["slot"] == 1
        and angles[0]["kind"] == "headline_first",
        "important_angles_invalid",
    )
    require(
        isinstance(angles[1], dict)
        and set(angles[1]) == {"slot", "kind", "index", "fact_sha256"}
        and type(angles[1]["slot"]) is int
        and angles[1]["slot"] == 2
        and angles[1]["kind"] == "context_first"
        and type(angles[1]["index"]) is int
        and 0 <= angles[1]["index"] < 100,
        "important_angles_invalid",
    )
    for angle in angles:
        _sha(angle["fact_sha256"])
    require(angles[0]["fact_sha256"] != angles[1]["fact_sha256"], "important_angles_identical")
    checks = value["check_reservations"]
    require(
        isinstance(checks, dict) and set(checks) == {"safety", "fact_check", "critic"},
        "important_reservation_invalid",
    )
    for role, reservation in [("writer", value["writer_reservation"]), *checks.items()]:
        require(
            isinstance(reservation, dict)
            and set(reservation)
            == {"estimate_sha256", "reserve_micro_usd", "provider", "model", "role"},
            "important_reservation_invalid",
        )
        _sha(reservation["estimate_sha256"])
        require(
            type(reservation["reserve_micro_usd"]) is int
            and 0 < reservation["reserve_micro_usd"] <= 10**12
            and reservation["role"] == role
            and reservation["provider"] == ("anthropic" if role == "writer" else "google")
            and isinstance(reservation["model"], str)
            and 0 < len(reservation["model"]) <= 160,
            "important_reservation_invalid",
        )
    ceiling = value["writer_reservation"]["reserve_micro_usd"] + 2 * sum(
        r["reserve_micro_usd"] for r in checks.values()
    )
    require(
        type(value["max_group_commitment_micro_usd"]) is int
        and value["max_group_commitment_micro_usd"] == ceiling,
        "important_limit_invalid",
    )
    return value


def angle_facts(bundle, allowance):
    """Retained fact identity only; safe for passive historical plan reads."""
    index = allowance["angles"][1]["index"]
    require(index < len(bundle.current_facts), "important_angle_fact_missing")
    headline, fact = bundle.headline_metric, bundle.current_facts[index]
    _fact(headline)
    aqi = (
        bundle.signal_kind == "air_quality_hazard"
        and isinstance(fact, dict)
        and fact.get("label") == "us_aqi_daily_max"
        and "unit" not in fact
    )
    if aqi:
        require(
            type(fact.get("value")) is int
            and fact["value"] >= 0
            and sum(
                isinstance(row, dict) and row.get("label") == "us_aqi_daily_max"
                for row in bundle.current_facts
            )
            == 1,
            "important_aqi_fact_invalid",
        )
    else:
        _fact(fact)
    require(
        fingerprint(headline) == allowance["angles"][0]["fact_sha256"]
        and fingerprint(fact) == allowance["angles"][1]["fact_sha256"]
        and (
            aqi
            or {k: headline[k] for k in ("label", "value", "unit")}
            != {k: fact[k] for k in ("label", "value", "unit")}
        ),
        "important_angle_changed",
    )
    return headline, fact, aqi


def context_anchor(bundle, fact, *, aqi):
    if not aqi:
        return fact
    # Current request construction only. The caller also runs the full existing
    # scientific reconstruction; historical plan/cost reads never enter here.
    from src.data import air_quality_contract as aq
    from src.data.source_status import SourceFetchError

    window = bundle.raw_signal_dump.get("forecast_window")
    try:
        totals = aq.validate_window(window)
    except (SourceFetchError, TypeError, ValueError, KeyError):
        raise ImportantContractError("important_aqi_window_invalid") from None
    entry = window["series"]["us_aqi"]
    require(
        entry["status"] == "complete"
        and entry["unit"] == "US AQI"
        and type(totals["us_aqi"]) is int
        and totals["us_aqi"] == fact["value"],
        "important_aqi_window_invalid",
    )
    return dict(
        fact,
        unit=entry["unit"],
        forecast_scope={
            key: deepcopy(window[key])
            for key in (
                "requested_location",
                "date",
                "timezone",
                "valid_start",
                "valid_end",
                "source_product",
                "source_url",
                "evidence_type",
                "domain_selection",
                "method",
            )
        },
        qualification="Co-reported modeled city-local forecast-day US AQI maximum; not a station observation, measured exposure, or evidence that PM2.5 caused this AQI value. Exact model, run and resolution are unknown.",
    )


def requests_for(bundle, memory, policy, allowance):
    allowance_document(allowance)
    require(
        valid_policy(policy)
        and policy["flags"]["writer_samples"] == 1
        and policy["flags"]["critic_revise_enabled"] is False,
        "important_policy_invalid",
    )
    require(
        audit_story_bundle(bundle).prompt_ready
        and bundle.signal_kind not in writer.OUT_OF_SCOPE_SIGNAL_KINDS,
        "important_evidence_not_ready",
    )
    require(
        allowance["context"]["bundle_sha256"] == fingerprint(bundle.to_dict())
        and allowance["context"]["memory_sha256"] == fingerprint(memory.to_dict())
        and allowance["context"]["policy_sha256"] == fingerprint(policy),
        "important_context_changed",
    )
    for role, reservation in [
        ("writer", allowance["writer_reservation"]),
        *allowance["check_reservations"].items(),
    ]:
        require(reservation["model"] == policy["models"][role], "important_model_changed")
    headline, fact, aqi = angle_facts(bundle, allowance)
    context = context_anchor(bundle, fact, aqi=aqi)
    base = writer.build_writer_user_prompt(bundle, memory)
    params = []
    for angle, fact in zip(allowance["angles"], (headline, context), strict=True):
        suffix = (
            "\n\nImportant-event angle: "
            + angle["kind"]
            + ". Lead with this retained fact: "
            + canonical(fact).decode()
            + ". Preserve all qualifiers and source limits. Do not invent an impact. Do not expand the tweet to use spare space."
        )
        request = writer.anthropic_writer_request(base + suffix)
        require(
            request["model"] == policy["models"]["writer"]
            and writer.WRITER_PROVIDER == "anthropic",
            "important_model_changed",
        )
        params.append(request)
    return params


def prepare_plan(bundle, memory, *, policy, allowance, job_id, created_at, useful_until):
    params = requests_for(bundle, memory, policy, allowance)
    binding = dict(
        schema_version=2,
        kind=KIND,
        job_id=job_id,
        **allowance["context"],
        created_at=created_at,
        useful_until=useful_until,
        minimum_window_seconds=3600,
        samples=2,
        experiment_id=None,
        policy=deepcopy(policy),
        params_sha256=fingerprint(
            [dict(slot=i + 1, params_sha256=fingerprint(p)) for i, p in enumerate(params)]
        ),
        allowance=deepcopy(allowance),
        allowance_sha256=digest(allowance),
        bundle=bundle.to_dict(),
        memory=memory.to_dict(),
    )
    plan = dict(
        binding,
        requests=[
            dict(
                custom_id="th_" + fingerprint(dict(binding=binding, sample_index=i))[:60], params=p
            )
            for i, p in enumerate(params)
        ],
    )
    validate_plan(plan)
    return canonical(plan)


def validate_plan(plan):
    require(
        isinstance(plan, dict)
        and set(plan) == PLAN_FIELDS
        and type(plan["schema_version"]) is int
        and plan["schema_version"] == 2
        and plan["kind"] == KIND,
        "important_plan_invalid",
    )
    require(
        type(plan["samples"]) is int
        and plan["samples"] == 2
        and plan["experiment_id"] is None
        and type(plan["minimum_window_seconds"]) is int
        and plan["minimum_window_seconds"] == 3600,
        "important_plan_invalid",
    )
    require(
        isinstance(plan["job_id"], str) and re.fullmatch(r"iv_[0-9a-f]{64}", plan["job_id"]),
        "important_job_invalid",
    )
    allowance = allowance_document(plan["allowance"])
    require(
        digest(allowance) == plan["allowance_sha256"]
        and all(plan[k] == allowance["context"][k] for k in CONTEXT),
        "important_allowance_changed",
    )
    start, end = utc_datetime(plan["created_at"]), utc_datetime(plan["useful_until"])
    require(
        utc_text(start) == plan["created_at"]
        and utc_text(end) == plan["useful_until"]
        and utc_datetime(allowance["valid_from"]) <= start
        and end <= utc_datetime(allowance["valid_until"])
        and (end - start).total_seconds() > 3600,
        "important_window_invalid",
    )
    bundle, memory = retained_bundle(plan["bundle"]), MemorySlice(**deepcopy(plan["memory"]))
    require(
        bundle.to_dict() == plan["bundle"] and memory.to_dict() == plan["memory"],
        "important_inputs_changed",
    )
    angle_facts(bundle, allowance)
    # Historical journal reads validate the retained request identity without
    # depending on today's loaded prompt/model. Authority registration and every
    # dispatch recompute prepare_plan from the current qualified inputs/policy.
    require(
        valid_policy(plan["policy"])
        and plan["policy"]["flags"]["writer_samples"] == 1
        and plan["policy"]["flags"]["critic_revise_enabled"] is False
        and fingerprint(plan["policy"]) == plan["policy_sha256"]
        and fingerprint(bundle.to_dict()) == plan["bundle_sha256"]
        and fingerprint(memory.to_dict()) == plan["memory_sha256"],
        "important_context_changed",
    )
    require(
        isinstance(plan["requests"], list) and len(plan["requests"]) == 2,
        "important_requests_changed",
    )
    params = []
    for row in plan["requests"]:
        require(
            isinstance(row, dict)
            and set(row) == {"custom_id", "params"}
            and isinstance(row["params"], dict),
            "important_requests_changed",
        )
        request = row["params"]
        require(
            request.get("model") == plan["policy"]["models"]["writer"]
            and isinstance(request.get("messages"), list)
            and isinstance(request.get("system"), list)
            and isinstance(request.get("output_config"), dict)
            and type(request.get("max_tokens")) is int
            and 0 < request["max_tokens"] <= 32768,
            "important_params_changed",
        )
        params.append(request)
    require(
        plan["params_sha256"]
        == fingerprint(
            [dict(slot=i + 1, params_sha256=fingerprint(p)) for i, p in enumerate(params)]
        ),
        "important_params_changed",
    )
    binding = {k: v for k, v in plan.items() if k != "requests"}
    expected = [
        dict(custom_id="th_" + fingerprint(dict(binding=binding, sample_index=i))[:60], params=p)
        for i, p in enumerate(params)
    ]
    require(plan["requests"] == expected, "important_requests_changed")
    return plan
