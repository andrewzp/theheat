"""Exercise actual failure boundaries with hostile private-data sentinels."""

import io
import json

import pytest

from src.dashboard_preview.errors import PreviewError, log_unavailable
from src.dashboard_preview.reader import Budget, read_gist
from tests.dashboard_graphic_helpers import saved_preview
from tests.test_dashboard_graphic_auth import AUTH
from tests.test_dashboard_graphic_http import endpoint as endpoint
from tests.test_dashboard_graphic_reader import ENV, RAW, Response, Session, api_response

PRIVATE = "DO-NOT-LOG-private-token-source-text-and-request-path"


class BrokenLog(io.StringIO):
    def write(self, value):
        raise OSError(PRIVATE)


@pytest.mark.parametrize("stage", [PRIVATE, [], {}, None, 42])
def test_unknown_diagnostic_input_is_silent(stage, capsys):
    log_unavailable(stage, http_status=PRIVATE)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("status", [True, 99, 600, PRIVATE, None])
def test_only_bounded_exact_integer_status_can_be_recorded(status, capsys):
    log_unavailable("state_raw_http", http_status=status)
    assert json.loads(capsys.readouterr().err) == {"component": "graphic_preview", "stage": "state_raw_http"}


@pytest.mark.parametrize("stage", ["authorization", "request", "state_read", "render"])
@pytest.mark.parametrize("broken_logging", [False, True])
def test_real_http_boundary_keeps_exact_private_response_and_releases_busy_lock(
        endpoint, monkeypatch, capsys, stage, broken_logging):
    state, request = saved_preview()

    def failure(*_a, **_k):
        raise RuntimeError(PRIVATE)

    if stage == "authorization":
        monkeypatch.setenv("DASHBOARD_USERNAME", "")
    elif stage == "request":
        monkeypatch.setattr("src.dashboard_preview.http.strict_json", failure)
    elif stage == "state_read":
        # The real build_preview validates the request then invokes current_state.
        monkeypatch.setattr("src.dashboard_preview.http.read_gist", failure)
    else:
        monkeypatch.setattr("src.dashboard_preview.http.build_preview", failure)
    with monkeypatch.context() as logging:
        if broken_logging:
            logging.setattr("src.dashboard_preview.errors.sys.stderr", BrokenLog())
        status, _, body = endpoint(body=json.dumps(request).encode(), headers={"Authorization": AUTH})
    assert status == 503 and body == PreviewError("preview_unavailable").payload()
    output = capsys.readouterr()
    assert PRIVATE not in output.out + output.err + json.dumps(body)
    records = [json.loads(line) for line in output.err.splitlines()]
    assert records == ([] if broken_logging else [{"component": "graphic_preview", "stage": stage}])
    from src.dashboard_preview.http import _BUSY
    assert _BUSY.acquire(blocking=False)
    _BUSY.release()
    assert state["drafts"][0]["status"] == "pending"


@pytest.mark.parametrize("case,expected,status", [
    ("configuration", ["state_configuration"], None),
    ("metadata_http", ["state_metadata_http", "state_metadata_body", "state_metadata_read"], 403),
    ("raw_http", ["state_raw_http", "state_raw_body", "state_raw_read"], 404),
    ("metadata_exception", ["state_metadata_send", "state_metadata_read"], None),
    ("state_json", ["state_json"], None),
])
def test_real_reader_distinguishes_fixed_failure_stages_without_retries_or_private_values(
        monkeypatch, capsys, case, expected, status):
    responses = {
        "metadata_http": [Response(PRIVATE.encode(), 403)],
        "raw_http": [api_response(truncated=True, raw_url=RAW), Response(PRIVATE.encode(), 404)],
        "state_json": [api_response(content=PRIVATE)],
    }
    session = Session(responses.get(case, []))
    if case == "metadata_exception":
        def failure(*_a, **_k):
            raise RuntimeError(PRIVATE)
        session.get = failure
    monkeypatch.setattr("requests.Session", lambda: session)
    env = {**ENV, "GITHUB_TOKEN": PRIVATE}
    if case == "configuration":
        env["GIST_ID"] = PRIVATE
    with pytest.raises(PreviewError) as error:
        read_gist(env, Budget())
    assert error.value.payload() == PreviewError("preview_unavailable").payload()
    output = capsys.readouterr()
    assert PRIVATE not in output.out + output.err
    records = [json.loads(line) for line in output.err.splitlines()]
    assert [r["stage"] for r in records] == expected
    assert all(set(r) <= {"component", "stage", "http_status", "error_code"} and r["component"] == "graphic_preview" for r in records)
    assert [r["http_status"] for r in records if "http_status" in r] == ([] if status is None else [status])
    assert len(session.calls) == (2 if case == "raw_http" else 1 if case in {"metadata_http", "state_json"} else 0)


def test_invalid_request_does_not_log_its_body_headers_or_path(endpoint, capsys):
    assert endpoint(body=PRIVATE.encode(), headers={"Authorization": AUTH},
                    path="/api/graphic_preview?private=" + PRIVATE)[0] == 400
    assert capsys.readouterr().err == ""
