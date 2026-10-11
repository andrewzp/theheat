import io
import json

import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.reader import Budget, _body, read_gist, strict_json

GIST = "0123456789abcdef0123456789abcdef"
ENV = {"GIST_ID": GIST, "GITHUB_TOKEN": "fixture-secret"}
RAW = f"https://gist.githubusercontent.com/editor/{GIST}/raw/{'a' * 40}/state.json"


class Response:
    def __init__(self, body, status=200):
        self.raw, self.status_code = io.BytesIO(body), status
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.raw.close()


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []
        self.trust_env = True
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def api_response(**changes):
    file = {"filename": "state.json", "truncated": False, "content": '{"drafts":[]}', **changes}
    return Response(json.dumps({"id": GIST, "files": {"state.json": file}}).encode())


def test_raw_fetch_uses_only_validated_versioned_url_without_credentials(monkeypatch):
    session = Session([api_response(truncated=True, raw_url=RAW), Response(b'{"drafts":[]}')])
    monkeypatch.setattr("requests.Session", lambda: session)
    assert read_gist(ENV, Budget()) == {"drafts": []}
    assert not session.trust_env and len(session.calls) == 2
    assert session.calls[0][1]["headers"]["Authorization"] == "token fixture-secret"
    assert "Authorization" not in session.calls[1][1]["headers"]
    assert session.calls[1][0] == RAW
    assert all(not kwargs["allow_redirects"] and kwargs["stream"] and kwargs["timeout"] == (2, 3)
               for _, kwargs in session.calls)


def test_explicit_gist_wins_over_sqlite_default(monkeypatch):
    session = Session([api_response()])
    monkeypatch.setattr("requests.Session", lambda: session)
    assert read_gist({**ENV, "THEHEAT_STATE_BACKEND": " GIST ", "THEHEAT_DB_PATH": "unused"}, Budget()) == {"drafts": []}


@pytest.mark.parametrize("changes", [{"THEHEAT_DB_PATH": "unused"}, {"THEHEAT_STATE_BACKEND": "postgres"},
                                     {"GITHUB_TOKEN": ""}, {"GIST_ID": "../private"}])
def test_configuration_fails_before_network(monkeypatch, changes):
    monkeypatch.setattr("requests.Session", lambda: pytest.fail("network before config"))
    with pytest.raises(PreviewError):
        read_gist({**ENV, **changes}, Budget())


@pytest.mark.parametrize("url", [RAW + "?token=x", RAW + "#x", RAW.replace("https:", "http:"),
    RAW.replace(GIST, "b" * 32), RAW.replace("/raw/" + "a" * 40, "/raw"),
    RAW.replace("gist.githubusercontent.com", "gist.githubusercontent.com.evil.example"),
    RAW.replace("gist.githubusercontent.com", "name:secret@gist.githubusercontent.com"),
    RAW.replace("state.json", "other.json")])
def test_untrusted_raw_locations_never_requested(monkeypatch, url):
    session = Session([api_response(truncated=True, raw_url=url)])
    monkeypatch.setattr("requests.Session", lambda: session)
    with pytest.raises(PreviewError):
        read_gist(ENV, Budget())
    assert len(session.calls) == 1


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
                                  b'{"x":1e999}', b'{"x":"\\ud800"}', b'\xff', b'[]',
                                  b'{"x":' + b'[' * 66 + b'0' + b']' * 66 + b'}'])
def test_strict_json_rejects_ambiguous_or_unbounded_values(raw):
    with pytest.raises(PreviewError):
        strict_json(raw, 10000)


def test_body_overflow_redirect_and_deadline_are_not_retried():
    for response in (Response(b"x" * 11), Response(b"secret upstream detail", 302)):
        session = Session([response])
        with pytest.raises(PreviewError):
            _body(session, "https://fixture.invalid", {}, 10, Budget())
        assert len(session.calls) == 1
    times = iter([0, 0, 24, 26])
    session = Session([Response(b"x")])
    with pytest.raises(PreviewError):
        _body(session, "https://fixture.invalid", {}, 10, Budget(clock=lambda: next(times)))
    assert len(session.calls) == 1


def test_raw_state_bound_and_errors_are_redacted(monkeypatch):
    session = Session([api_response(content="x" * 100)])
    monkeypatch.setattr("requests.Session", lambda: session)
    monkeypatch.setattr("src.dashboard_preview.reader.STATE_LIMIT", 20)
    with pytest.raises(PreviewError) as error:
        read_gist(ENV, Budget())
    assert "xxxxxxxx" not in str(error.value) and "fixture-secret" not in str(error.value)
