"""Fixed public errors; never expose private input or provider exception text."""

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
