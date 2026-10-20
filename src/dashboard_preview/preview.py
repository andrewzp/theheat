"""Select the exact saved draft twice; a preview never changes state or grants review."""

from copy import deepcopy
import json
import re

from src.dashboard_preview.errors import PreviewError
from src.editorial.revisions import decision_revision, draft_identity, fingerprint, has_unresolved_publish
from src.media.air_quality_graphic_adapter import pm25_graphic_spec
from src.media.fire_map_graphic_adapter import fire_map_graphic_spec
from src.media.evidence_graphic_render import render_svg
from src.media.temperature_graphic_adapter import _StoredBundle
from src.media.viirs_map_graphic_adapter import PLATFORMS as VIIRS_PRODUCTS, viirs_map_graphic_spec

MAX_RESPONSE = 1024 * 1024
SHA = re.compile(r"[a-f0-9]{64}")
REQUEST_KEYS = {"draft_id", "expected_revision", "expected_policy_source_sha256", "expected_preview_runtime_sha256"}
REVISION_KEYS = {"content_revision", "text_sha256", "evidence_sha256", "decision_revision"}


def check_request(request, policy_sha, runtime_sha):
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
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


def qualified_spec(bundle, *, synthetic=False, include_viirs=False):
    """Shared Python qualification; callers own authentication/currentness.

    VIIRS is opt-in. Only the saved-draft preview route enables it; other callers
    keep their reviewed MODIS/PM2.5 scope until they adopt the VIIRS template and
    its display-limit preflight explicitly. Dispatch reads the retained primary
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
    raise PreviewError("graphic_unavailable")


def build_preview(request, *, policy_sha, runtime_sha, read_state, budget, synthetic=False):
    check_request(request, policy_sha, runtime_sha)
    try:
        budget.remaining()
        draft = _selected(read_state(), request)
        original_status = draft["status"]
        bundle = deepcopy(draft["review_context"]["two_bot"]["bundle"])
        # Bound the full retained story before canonical hashing and validation.
        retained_bundle = _retained_bundle_json(bundle)
        spec, source, context = qualified_spec(bundle, synthetic=synthetic, include_viirs=True)
        budget.remaining()
        rendered = render_svg(**spec)
        budget.remaining()
        current = _selected(read_state(), request)
        if (current["status"] != original_status
                or _retained_bundle_json(current["review_context"]["two_bot"]["bundle"],
                                         code="stale_preview") != retained_bundle):
            raise PreviewError("stale_preview")
        budget.remaining()
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
            raise PreviewError("graphic_unavailable")
        return body
    except PreviewError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise PreviewError("graphic_unavailable") from exc
