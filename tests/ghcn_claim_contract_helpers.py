"""Invented passive-claim parity cases; no source acquisition or authority."""

from copy import deepcopy
from hashlib import sha256
import json

from src.editorial.revisions import fingerprint
from src.two_bot.json_utils import json_default
from tests.ghcn_graphic_helpers import graphic_bundles

VARIANTS = [
    (direction, tier)
    for direction in ("high", "low")
    for tier in ("all_time", "monthly", "calendar")
]


def reference(full, field):
    run = "00000000-0000-4000-8000-000000000001"
    evidence = full.raw_signal_dump["evidence"]

    def pin(name):
        return sha256(("invented-" + name).encode()).hexdigest()

    return dict(
        schema_version=1,
        kind="ghcn_claim_view_v1",
        scope="selected_claim_warrants",
        source_run_id=run,
        source_result=dict(
            namespace="ghcn-source-runtime-result-v1",
            snapshot_id="run:" + run,
            sha256=pin("result"),
        ),
        runtime_input=dict(
            namespace="ghcn-source-result-input-v1", snapshot_id="run:" + run, sha256=pin("input")
        ),
        scientific_supply=dict(
            namespace="scientific-supply-ghcn-v1", snapshot_id="run:" + run, sha256=pin("supply")
        ),
        selection=dict(
            station_id=evidence["station_id"], signal_date=full.when, signal_field=field
        ),
        member_sha256=pin("member"),
        full_story=dict(
            codec="revision-fingerprint-v1-json-default",
            sha256=fingerprint(json.loads(json.dumps(full.to_dict(), default=json_default))),
        ),
        observation_revision=evidence["revision_id"],
        baseline_revision=evidence["baseline"]["revision_id"],
        baseline_artifact=dict(database_sha256=pin("database"), manifest_sha256=pin("manifest")),
        original_archives=[
            dict(
                kind="station_archive",
                key=evidence["station_id"],
                retrieved_at=evidence["retrieved_at"],
                status="success",
                raw_sha256=evidence["baseline"]["source_payload_sha256"],
                failure_code=None,
            )
        ],
    )


def pair(claim, direction="high", tier="all_time"):
    full = graphic_bundles(direction=direction, tier=tier)[-1]
    field = f"{tier}_{direction}" if tier != "calendar" else f"calendar_date_{direction}"
    ref = reference(full, field)
    view = claim.json_tree(claim.project(full, ref, ref["selection"]).to_dict())
    return full, claim.json_tree(full.to_dict()), view, ref


def signature(value):
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return dict(
        sha256=sha256(raw).hexdigest(), byte_length=len(raw), fingerprint=fingerprint(value)
    )


def outcome(call, *args):
    try:
        return dict(status="returned", value=signature(call(*args)))
    except Exception as exc:
        return dict(
            status="error",
            exception=f"{type(exc).__module__}.{type(exc).__name__}",
            message=str(exc),
            code=getattr(exc, "code", None),
        )


def structural_cases(view):
    cases = {}
    for name in (
        "missing_field",
        "extra_field",
        "empty_optional",
        "oversize",
        "missing_reference",
        "reference_extra",
        "schema_bool",
        "uuid",
        "selection",
        "date",
        "namespace",
        "snapshot",
        "sha",
        "codec",
        "baseline_pin",
        "archive_count",
        "archive_key",
        "nonfinite",
        "unicode",
        "large_integer",
        "negative_zero",
    ):
        value = deepcopy(view)
        ref = value["raw_signal_dump"]["ghcn_claim_view"]
        if name == "missing_field":
            del value["where"]
        elif name == "extra_field":
            value["unknown"] = True
        elif name == "empty_optional":
            value["country"] = ""
        elif name == "oversize":
            value["current_facts"].append(dict(label="invented", value="x" * 32768))
        elif name == "missing_reference":
            del value["raw_signal_dump"]["ghcn_claim_view"]
        elif name == "reference_extra":
            ref["unknown"] = True
        elif name == "schema_bool":
            ref["schema_version"] = True
        elif name == "uuid":
            ref["source_run_id"] = "not-a-uuid"
        elif name == "selection":
            ref["selection"]["signal_field"] = "forecast_high"
        elif name == "date":
            ref["selection"]["signal_date"] = "2032-02-31"
        elif name == "namespace":
            ref["source_result"]["namespace"] = "another-source"
        elif name == "snapshot":
            ref["runtime_input"]["snapshot_id"] = "run:another"
        elif name == "sha":
            ref["member_sha256"] = "A" * 64
        elif name == "codec":
            ref["full_story"]["codec"] = "other-codec"
        elif name == "baseline_pin":
            ref["baseline_artifact"]["database_sha256"] = None
        elif name == "archive_count":
            ref["original_archives"] *= 2
        elif name == "archive_key":
            ref["original_archives"][0]["key"] = "other-station"
        else:
            value["current_facts"].append(
                dict(
                    label="invented",
                    value={
                        "nonfinite": float("nan"),
                        "unicode": "\ud800",
                        "large_integer": 2**53 + 1,
                        "negative_zero": -0.0,
                    }[name],
                )
            )
        cases[name] = value
    return cases


def projection_cases(full_json):
    cases = {}
    for name in (
        "evidence_extra",
        "source",
        "baseline_extra",
        "variables",
        "variable_extra",
        "table_type",
        "record_shape",
        "historical_mismatch",
        "nonfinite",
    ):
        value = deepcopy(full_json)
        evidence = value["raw_signal_dump"]["evidence"]
        baseline = evidence["baseline"]
        if name == "evidence_extra":
            evidence["unknown"] = True
        elif name == "source":
            evidence["source_product"] = "another-source"
        elif name == "baseline_extra":
            baseline["unknown"] = True
        elif name == "variables":
            baseline["variables"]["unknown"] = {}
        elif name == "variable_extra":
            baseline["variables"]["temperature_2m_max"]["unknown"] = True
        elif name == "table_type":
            baseline["variables"]["temperature_2m_max"]["monthly_years"] = []
        elif name == "record_shape":
            baseline["variables"]["temperature_2m_max"]["record_dates"]["monthly"] = []
        elif name == "nonfinite":
            value["headline_metric"]["value"] = float("inf")
        if name != "historical_mismatch":
            value["historical_context"]["baseline"] = deepcopy(baseline)
        else:
            value["historical_context"]["baseline"] = {}
        cases[name] = value
    return cases
