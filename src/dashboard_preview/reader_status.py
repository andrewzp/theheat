"""Protected, bounded state-reader status; never selects a draft or renders."""

import json
import os

from src.dashboard_preview.auth import authorize, header
from src.dashboard_preview.errors import PreviewError, failure_code, log_unavailable, reader_failure_stage
from src.dashboard_preview.http import _BUSY, handler_type as preview_handler_type
from src.dashboard_preview.reader import Budget, read_gist

PATHS = frozenset({"/api/graphic_reader_status", "/api/graphic_reader_status.py"})


def _result(available, *, error=None):
    value = {"schema_version": 1, "state_reader": "available" if available else "unavailable",
             "rendering": "not_evaluated", "source_qualification": "not_evaluated",
             "publication_approved": False}
    if error is not None:
        value["failure_code"] = failure_code(error)
        value["reader_stage"] = reader_failure_stage(error)
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def handler_type(*, policy_sha, runtime_sha):
    parent = preview_handler_type(policy_sha=policy_sha, runtime_sha=runtime_sha)

    class ReaderStatusHandler(parent):  # type: ignore[valid-type,misc]
        _allowed_method = "GET"

        def _handle(self):
            acquired = False
            stage = "authorization"
            try:
                # Caller-specific fixed paths, with the same independent auth and
                # host/origin checks as the preview. The request cannot choose scope.
                authorize(self.path, self.headers, os.environ, paths=PATHS)
                stage = "request"
                if self.command != "GET":
                    raise PreviewError("method_not_allowed")
                if (header(self.headers, "Transfer-Encoding") or header(self.headers, "Content-Encoding")
                        or header(self.headers, "Content-Length") not in {"", "0"}):
                    raise PreviewError("bad_request")
                acquired = _BUSY.acquire(blocking=False)
                if not acquired:
                    raise PreviewError("preview_busy")
                budget = Budget()
                self.connection.settimeout(min(3, budget.remaining()))
                stage = "state_read"
                # One complete existing reader call. No draft/source selection,
                # second read, model call, renderer, storage mutation or fallback.
                read_gist(os.environ, budget)
                budget.remaining()
                self._reply(200, _result(True))
            except PreviewError as exc:
                if exc.status == 503 and stage == "state_read":
                    code = failure_code(exc)
                    log_unavailable(stage, error_code=code)
                    self._reply(503, _result(False, error=exc))
                else:
                    if exc.status == 503:
                        log_unavailable(stage)
                    self._reply(exc.status, json.dumps(exc.payload()).encode("utf-8"),
                                authenticate=exc.status == 401)
            except Exception as exc:
                log_unavailable(stage, error_code=failure_code(exc))
                unavailable = (_result(False, error=exc) if stage == "state_read"
                               else json.dumps(PreviewError("preview_unavailable").payload()).encode("utf-8"))
                self._reply(503, unavailable)
            finally:
                if acquired:
                    _BUSY.release()

        do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _handle

    return ReaderStatusHandler
