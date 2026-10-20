"""Fixed public errors and allowlisted diagnostics without private input."""

import json
import sys

_DIAGNOSTIC_STAGES = frozenset({
    "authorization", "request", "state_read", "render",
    "state_configuration", "state_metadata_read", "state_metadata_shape",
    "state_raw_read", "state_json", "state_metadata_http", "state_raw_http",
})


def log_unavailable(stage, *, http_status=None):
    """Fixed internal failure records only; failed logging cannot change a reply."""
    if type(stage) is not str or stage not in _DIAGNOSTIC_STAGES:
        return
    record: dict[str, str | int] = {"component": "graphic_preview", "stage": stage}
    if type(http_status) is int and 100 <= http_status <= 599:
        record["http_status"] = http_status
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
}


class PreviewError(Exception):
    def __init__(self, code):
        self.code = code
        self.status, message = ERRORS[code]
        super().__init__(message)

    def payload(self):
        return {"code": self.code, "error": str(self)}
