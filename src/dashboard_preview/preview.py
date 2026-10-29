"""Select the exact saved draft twice; a preview never changes state or grants review."""

from copy import deepcopy
import base64
import json
import re
from typing import cast

from src.dashboard_preview.errors import PreviewError
from src.editorial.revisions import decision_revision, draft_identity, fingerprint, has_unresolved_publish
from src.media.air_quality_graphic_adapter import pm25_graphic_spec
from src.media.fire_map_graphic_adapter import fire_map_graphic_spec
from src.media.evidence_graphic_render import render_svg
from src.media.temperature_graphic_adapter import _StoredBundle, temperature_graphic_spec
from src.media.viirs_map_graphic_adapter import PLATFORMS as VIIRS_PRODUCTS, viirs_map_graphic_spec
from src.two_bot.types import StoryBundle

MAX_RESPONSE = 1024 * 1024
MEDIA_TEMPERATURE = "gist_temperature_comparator_v1"
SHA = re.compile(r"[a-f0-9]{64}")
REQUEST_KEYS = {"draft_id", "expected_revision", "expected_policy_source_sha256", "expected_preview_runtime_sha256"}
REVISION_KEYS = {"content_revision", "text_sha256", "evidence_sha256", "decision_revision"}


def check_request(request, policy_sha, runtime_sha):
    # A retained-input identity (CRW source packet or published asset manifest) is
    # only meaningful for the PNG post image; it is an exact SHA256, never a path/URL.
    if (not isinstance(request, dict)
            or set(request) not in (REQUEST_KEYS, REQUEST_KEYS | {"format"}, REQUEST_KEYS | {"format", "retained_input_sha256"})
            or ("format" in request and request["format"] != "png")
            or ("retained_input_sha256" in request and not (isinstance(request["retained_input_sha256"], str)
                                                            and SHA.fullmatch(request["retained_input_sha256"])))):
        raise PreviewError("bad_request")
    draft_id, revision = request["draft_id"], request["expected_revision"]
    if (not isinstance(draft_id, str) or not 0 < len(draft_id) <= 200
            or any(ord(c) < 32 for c in draft_id)
            or not isinstance(revision, dict) or set(revision) != REVISION_KEYS):
        raise PreviewError("bad_request")
    for key in ("content_revision", "decision_revision"):
        maximum = 9007199254740991 if key == "content_revision" else 9007199254740990
        if type(revision[key]) is not int or not 0 <= revision[key] <= maximum:
            raise PreviewError("bad_request")
    for value in (revision["text_sha256"], revision["evidence_sha256"],
                  request["expected_policy_source_sha256"], request["expected_preview_runtime_sha256"]):
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise PreviewError("bad_request")
    if (request["expected_policy_source_sha256"] != policy_sha
            or request["expected_preview_runtime_sha256"] != runtime_sha):
        raise PreviewError("stale_preview")


def _selected(state, request):
    drafts = state.get("drafts")
    if not isinstance(drafts, list):
        raise PreviewError("draft_unavailable")
    matches = [d for d in drafts if isinstance(d, dict) and d.get("id") == request["draft_id"]]
    if len(matches) != 1:
        raise PreviewError("draft_unavailable")
    draft = matches[0]
    if draft.get("status") not in {"pending", "approved"}:
        raise PreviewError("draft_unavailable")
    if draft.get("revision_conflicts") or has_unresolved_publish(draft, state):
        raise PreviewError("conflicted_draft")
    identity = {**draft_identity(draft), "decision_revision": decision_revision(draft)}
    if identity != request["expected_revision"]:
        raise PreviewError("stale_preview")
    return draft


def _retained_bundle_json(bundle, *, code="graphic_unavailable"):
    # Editorial fingerprints deliberately normalize numeric types. The source
    # warrants do not: 500.0 -> 500 can invalidate a selected-record digest.
    encoded = json.dumps(bundle, sort_keys=True, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 1_000_000:
        raise PreviewError(code)
    return encoded


def qualified_spec(bundle, *, synthetic=False, include_viirs=False, include_temperature=False):
    """Shared Python qualification; callers own authentication/currentness.

    VIIRS and temperature comparisons are separately opt-in. The saved-draft
    preview and local editor enable them explicitly while retaining their own
    source-retention, authentication and currentness gates. Dispatch reads the retained
    primary
    product; the selected adapter then validates every row, so a mixed set holds.
    """
    _retained_bundle_json(bundle)
    if bundle["signal_kind"] == "fire":
        receipts = [bundle["raw_signal_dump"]["acquisition_provenance"],
                    *[r["acquisition_evidence"] for r in bundle.get("related_signals", [])]]
        options = dict(expected_bundle_sha256=fingerprint(bundle),
                       expected_receipt_sha256=[fingerprint(r) for r in receipts], synthetic=synthetic)
        if include_viirs and receipts[0]["source_product"] in VIIRS_PRODUCTS:
            spec = viirs_map_graphic_spec(_StoredBundle(bundle), **options)
            return spec, "NASA FIRMS · VIIRS", {"kind": "viirs_acquisition", "acquired_at": spec["evidence"]["acquired_at"]}
        spec = fire_map_graphic_spec(_StoredBundle(bundle), **options)
        return spec, "NASA FIRMS · MODIS", {"kind": "modis_acquisition", "acquired_at": spec["evidence"]["acquired_at"]}
    if bundle["signal_kind"] == "air_quality_hazard":
        spec = pm25_graphic_spec(_StoredBundle(bundle), expected_bundle_sha256=fingerprint(bundle),
                                expected_window_sha256=fingerprint(bundle["raw_signal_dump"]["forecast_window"]), synthetic=synthetic)
        evidence = spec["evidence"]
        window = evidence["input_binding"]["bundles"][0]["bundle"]["raw_signal_dump"]["forecast_window"]
        return spec, "CAMS via Open-Meteo", {"kind": "pm25_forecast_day",
            **{key: evidence[key] for key in ("valid_date", "timezone", "valid_start", "valid_end")},
            **{key: window[key] for key in ("requested_at", "retrieved_at")}}
    if include_temperature:
        # The adapter already replays this retained read-only StoryBundle facade;
        # it independently audits every field and warrant before projecting it.
        stored = cast(StoryBundle, _StoredBundle(bundle))
        spec = temperature_graphic_spec("temperature_comparator", [stored],
            expected_bundle_sha256=[fingerprint(bundle)], synthetic=synthetic)
        evidence = spec["evidence"]
        return spec, "NOAA GHCN-Daily · station observations", {
            "kind": "ghcn_station_day", "station_id": evidence["station_id"],
            "valid_date": evidence["points"][0]["valid_date"],
            "retrieved_at": evidence["evidence_as_of"],
            "reporting_interval_known": False, "timezone": None}
    raise PreviewError("graphic_unavailable")


def _store_backed_result(request, prepared, policy_sha, runtime_sha, bundle):
    """Schema 4 (CRW, a native chart) or schema 5 (published original + derivative)."""
    from src.media.gist_media import posting_window
    from src.media.gist_published_media import KINDS as PUBLISHED
    descriptor = prepared["descriptor"]
    common = {"draft_id": request["draft_id"], "revision_identity": deepcopy(request["expected_revision"]),
              "policy_source_sha256": policy_sha, "preview_runtime_sha256": runtime_sha,
              "media_kind": descriptor["kind"], "media_descriptor": descriptor,
              "media_descriptor_sha256": fingerprint(descriptor),
              "png_base64": base64.b64encode(prepared["png"]).decode("ascii"), "title": prepared["title"],
              "delivery_text": prepared["delivery_text"], "expanded_description": prepared["full_text"],
              "scope": prepared["scope"], "posting_window": posting_window(bundle, descriptor=descriptor),
              "publication_approved": False, "attachment": False}
    if descriptor["kind"] in PUBLISHED:
        asset = descriptor["asset"]
        return {"schema_version": 5, **common, "png_sha256": asset["derivative_sha256"],
                "original_base64": base64.b64encode(prepared["original"]).decode("ascii"),
                "original_sha256": asset["original_sha256"], "original_mime": asset["original_mime"],
                "inspection": prepared["inspection"], "width": asset["width"], "height": asset["height"]}
    source = descriptor["source"]
    evidence_as_of = bundle["raw_signal_dump"]["provenance"]["retrieved_at"]
    return {"schema_version": 4, **common, "png_sha256": descriptor["image"]["png_sha256"],
            "source": "NOAA Coral Reef Watch · daily 5 km SST anomaly v3.1",
            "source_context": {"kind": "crw_product_day", "product_date": source["product_date"],
                               "retrieved_at": evidence_as_of, "valid_cells": source["valid_cells"],
                               "total_cells": source["total_cells"]},
            "width": 1200, "height": 1500}


def build_preview(request, *, policy_sha, runtime_sha, read_state, budget, synthetic=False, store=None):
    check_request(request, policy_sha, runtime_sha)
    store_backed = False
    try:
        budget.remaining()
        draft = _selected(read_state(), request)
        original_status = draft["status"]
        bundle = deepcopy(draft["review_context"]["two_bot"]["bundle"])
        # Bound the full retained story before canonical hashing and validation.
        retained_bundle = _retained_bundle_json(bundle)
        from src.media import gist_media
        store_backed = request.get("format") == "png" and gist_media.needs_retained_input(bundle)
        if store_backed:
            spec = source = context = None
        else:
            if "retained_input_sha256" in request:
                raise PreviewError("bad_request")
            spec, source, context = qualified_spec(bundle, synthetic=synthetic, include_viirs=True,
                                                  include_temperature=True)
        budget.remaining()
        if request.get("format") == "png":
            prepared = gist_media.prepare_media(bundle, synthetic=synthetic, store=store,
                                                retained_input_sha256=request.get("retained_input_sha256"))
            rendered = None
        else:
            assert spec is not None
            rendered = render_svg(**spec)
        budget.remaining()
        current = _selected(read_state(), request)
        if (current["status"] != original_status
                or _retained_bundle_json(current["review_context"]["two_bot"]["bundle"],
                                         code="stale_preview") != retained_bundle):
            raise PreviewError("stale_preview")
        budget.remaining()
        if store_backed:
            result = _store_backed_result(request, prepared, policy_sha, runtime_sha, bundle)
        elif request.get("format") == "png" and prepared["descriptor"]["kind"] != MEDIA_TEMPERATURE:
            # New families: the bounded description sent to X and the expanded
            # source description stay separate. Posting disclosure is display-only;
            # approval and the sender recheck source time independently.
            from src.media.gist_media import posting_window
            descriptor = prepared["descriptor"]
            result = {"schema_version": 4, "draft_id": request["draft_id"],
                "revision_identity": deepcopy(request["expected_revision"]),
                "policy_source_sha256": policy_sha, "preview_runtime_sha256": runtime_sha,
                "media_kind": descriptor["kind"], "media_descriptor": descriptor,
                "media_descriptor_sha256": fingerprint(descriptor),
                "png_base64": base64.b64encode(prepared["png"]).decode("ascii"),
                "png_sha256": descriptor["image"]["png_sha256"], "title": prepared["title"],
                "delivery_text": prepared["delivery_text"], "expanded_description": prepared["full_text"],
                "scope": prepared["scope"], "source": source, "source_context": context,
                "posting_window": posting_window(bundle), "width": 1200, "height": 1500,
                "publication_approved": False, "attachment": False}
        elif request.get("format") == "png":
            descriptor = prepared["descriptor"]
            assert spec is not None
            result = {"schema_version": 3, "draft_id": request["draft_id"],
                "revision_identity": deepcopy(request["expected_revision"]),
                "policy_source_sha256": policy_sha, "preview_runtime_sha256": runtime_sha,
                "media_descriptor": descriptor, "media_descriptor_sha256": fingerprint(descriptor),
                "png_base64": base64.b64encode(prepared["png"]).decode("ascii"),
                "png_sha256": descriptor["png_sha256"], "title": prepared["title"],
                "alt_text": descriptor["alt_text"], "scope": spec["evidence"]["scope"],
                "source": source, "source_context": context, "width": 1200, "height": 1500,
                "publication_approved": False, "attachment": False}
        else:
            assert rendered is not None
            result = {"schema_version": 2, "draft_id": request["draft_id"],
                  "revision_identity": deepcopy(request["expected_revision"]),
                  "policy_source_sha256": policy_sha, "preview_runtime_sha256": runtime_sha,
                  "binding": rendered["binding"], "cache_key": rendered["cache_key"],
                  "svg_sha256": rendered["svg_sha256"], "svg_utf8": rendered["svg"].decode("utf-8"),
                  "title": rendered["title"], "alt_text": rendered["alt_text"], "scope": rendered["scope"],
                  "source": source, "source_context": context,
                  "width": rendered["width"], "height": rendered["height"],
                  "publication_approved": False, "attachment": False}
        body = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > MAX_RESPONSE:
            raise PreviewError("media_hold", "media_preview_too_large") if store_backed else PreviewError("graphic_unavailable")
        return body
    except PreviewError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError, OverflowError) as exc:
        # Store-backed lanes name their closed operator outcome; native lanes keep their reply.
        hold = getattr(exc, "code", None) if store_backed else None
        raise PreviewError("media_hold", hold) if hold else PreviewError("graphic_unavailable") from exc
