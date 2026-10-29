"""Fixed public errors and allowlisted diagnostics without private input."""

import json
import sys

import requests.exceptions as request_errors
import urllib3.exceptions as transport_errors

_DIAGNOSTIC_STAGES = frozenset({
    "authorization", "request", "state_read", "render",
    "state_configuration", "state_metadata_read", "state_metadata_shape",
    "state_raw_read", "state_json", "state_metadata_http", "state_raw_http",
    "state_metadata_send", "state_metadata_body", "state_metadata_json",
    "state_raw_send", "state_raw_body",
    "state_metadata_stream", "state_raw_stream",
})

_ERROR_TYPES = {
    request_errors.InvalidHeader: "invalid_header",
    request_errors.InvalidURL: "invalid_url",
    request_errors.MissingSchema: "invalid_url",
    request_errors.InvalidSchema: "invalid_url",
    request_errors.SSLError: "tls",
    request_errors.ConnectTimeout: "connect_timeout",
    request_errors.ReadTimeout: "read_timeout",
    request_errors.ConnectionError: "connection",
    request_errors.ChunkedEncodingError: "chunked_encoding",
    request_errors.ContentDecodingError: "content_decoding",
    request_errors.JSONDecodeError: "json_decode",
    request_errors.Timeout: "timeout",
    transport_errors.InvalidHeader: "invalid_header",
    transport_errors.LocationParseError: "invalid_url",
    transport_errors.SSLError: "tls",
    transport_errors.ConnectTimeoutError: "connect_timeout",
    transport_errors.NewConnectionError: "connection",
    transport_errors.NameResolutionError: "connection",
    transport_errors.ReadTimeoutError: "read_timeout",
    transport_errors.ProtocolError: "connection",
    transport_errors.DecodeError: "content_decoding",
    json.JSONDecodeError: "json_decode",
    ValueError: "value", UnicodeError: "value", UnicodeDecodeError: "value",
    UnicodeEncodeError: "value", TypeError: "type", AttributeError: "attribute",
    TimeoutError: "timeout", ConnectionError: "connection", OSError: "os",
}.items()
_ERROR_CODES = frozenset((*(code for _, code in _ERROR_TYPES), "preview_error", "unknown"))
_READER_STAGES = frozenset(stage for stage in _DIAGNOSTIC_STAGES if stage.startswith("state_"))


def reader_failure_stage(exc):
    """Only our exact exception can carry an allowlisted internal reader stage."""
    if type(exc) is PreviewError:
        stage = exc._reader_stage
        if type(stage) is str and stage in _READER_STAGES:
            return stage
    return "state_read"


def failure_code(exc):
    """Exact known classes only. Never inspect messages, names or a cause chain."""
    if type(exc) is PreviewError:
        kind, fallback = type(exc.__cause__), "preview_error"
    else:
        kind, fallback = type(exc), "unknown"
    # Identity comparison also avoids custom exception metaclass equality/hash.
    return next((code for known, code in _ERROR_TYPES if kind is known), fallback)


def log_unavailable(stage, *, http_status=None, error_code=None):
    """Fixed internal failure records only; failed logging cannot change a reply."""
    if type(stage) is not str or stage not in _DIAGNOSTIC_STAGES:
        return
    record: dict[str, str | int] = {"component": "graphic_preview", "stage": stage}
    if type(http_status) is int and 100 <= http_status <= 599:
        record["http_status"] = http_status
    if type(error_code) is str and error_code in _ERROR_CODES:
        record["error_code"] = error_code
    try:
        sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception:
        pass

ERRORS = {
    "bad_request": (400, "Refresh this draft and try the preview again."),
    "authentication_required": (401, "Sign in to preview this draft."),
    "sign_in_required": (403, "Open the protected dashboard address to preview this draft."),
    "origin_mismatch": (403, "Open the preview from this dashboard."),
    "draft_unavailable": (404, "This saved draft is no longer available. Refresh the queue."),
    "stale_preview": (409, "This draft changed. Refresh it before building another preview."),
    "conflicted_draft": (409, "Resolve this draft’s conflicting versions before previewing it."),
    "graphic_unavailable": (422, "The saved source evidence cannot support this graphic. Check the source details."),
    "preview_busy": (429, "Another preview is being built. Try again in a moment."),
    "preview_unavailable": (503, "The preview is unavailable. Your draft has not changed; try again later."),
    "method_not_allowed": (405, "Use the preview button in the dashboard."),
    "media_hold": (422, "This image is held. Your draft has not changed."),
}
# Closed operator outcomes for one image lane; fixed text only, never private input.
MEDIA_HOLDS = {
    "media_store_unavailable": "No media store is configured here for published or retained-source images; "
                               "native charts are unaffected.",
    "media_retained_input_required": "Select the retained source packet or published asset for this image.",
    "media_source_packet_missing": "The retained CRW source packet is not in the media store. Retain it locally "
                                   "first; nothing is fetched.",
    "media_original_missing": "The published original is not in the media store. Retain it again; nothing is "
                              "fetched.",
    "media_asset_missing": "A retained asset is missing from the media store.",
    "media_asset_changed": "Retained bytes no longer match their identity. Retain the asset again.",
    "media_asset_invalid": "The retained asset is unsupported or incomplete: rights, labels, times or format "
                           "are missing or changed.",
    "media_context_mismatch": "The retained image is not for this draft's source (storm, advisory, warning, "
                              "place or time).",
    "media_source_unqualified": "The saved source cannot support this image.",
    "media_source_future": "The retained source time is in the future.",
    "media_unsupported": "This source has no reviewed image product.",
    "media_renderer_changed": "The image profile changed; preview and review again.",
    "media_preview_too_large": "This image is too large to preview and send here.",
    "media_description_too_long": "The required image description does not fit the 1000-character limit; the "
                                  "text draft is unchanged.",
}


class PreviewError(Exception):
    def __init__(self, code, hold=None):
        self.code = code
        self._reader_stage: str | None = None
        self.status, message = ERRORS[code]
        self.hold = hold if code == "media_hold" and hold in MEDIA_HOLDS else None
        if code == "media_hold" and self.hold is None:
            self.code, (self.status, message) = "graphic_unavailable", ERRORS["graphic_unavailable"]
        super().__init__(MEDIA_HOLDS[self.hold] if self.hold else message)

    def payload(self):
        return {"code": self.code, "error": str(self), **({"hold": self.hold} if self.hold else {})}
