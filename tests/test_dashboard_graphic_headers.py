"""Invented credentials through actual request preparation, never external I/O."""

from copy import deepcopy
import json

import pytest
import requests
from urllib3 import exceptions as transport_errors

from src.dashboard_preview.errors import PreviewError, failure_code, reader_failure_stage
from src.dashboard_preview.reader import Budget, read_gist
from tests.test_dashboard_graphic_auth import AUTH
from tests.test_dashboard_graphic_reader import ENV, RAW
from tests.test_dashboard_graphic_transport import PRIVATE, install, metadata, wire
from tests.test_dashboard_reader_status import status_endpoint as status_endpoint


@pytest.mark.parametrize("truncated", [False, True], ids=["inline", "raw"])
@pytest.mark.parametrize("padding", [
    ("", ""), ("", "\n"), ("", "\r\n"), ("\n", ""),
    (" \t", "\r\n"), ("\r\n", "\t "),
], ids=["canonical", "trailing-lf", "trailing-crlf", "leading-lf", "mixed", "reverse-mixed"])
def test_http_whitespace_around_token_is_normalized(monkeypatch, capsys, padding, truncated):
    token = padding[0] + ENV["GITHUB_TOKEN"] + padding[1]
    env = {**ENV, "GITHUB_TOKEN": token}
    before = deepcopy(env)
    replies = ([wire(metadata(truncated=True, raw_url=RAW)), wire(b'{"drafts":[]}')]
               if truncated else [wire(metadata())])
    adapter = install(monkeypatch, *replies)
    assert read_gist(env, Budget()) == {"drafts": []}
    assert env == before  # Normalize the in-memory header, never stored configuration.
    assert len(adapter.calls) == (2 if truncated else 1)
    assert adapter.calls[0][0].headers["Authorization"] == "token " + ENV["GITHUB_TOKEN"]
    if truncated:
        assert adapter.calls[1][0].url == RAW
        assert "Authorization" not in adapter.calls[1][0].headers
    assert all(kwargs["stream"] and kwargs["timeout"] == (2, 3) for _, kwargs in adapter.calls)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("token", ['"fixture-secret"', "%66ixture-secret", "fixture.secret:+/_-=[]"])
def test_visible_token_bytes_are_never_unquoted_or_decoded(monkeypatch, token):
    adapter = install(monkeypatch, wire(metadata()))
    assert read_gist({**ENV, "GITHUB_TOKEN": token}, Budget()) == {"drafts": []}
    assert len(adapter.calls) == 1
    assert adapter.calls[0][0].headers["Authorization"] == "token " + token


@pytest.mark.parametrize("token", [
    "", " \t\r\n", None, 4, True, [], {},
    PRIVATE + "\r\nInjected: no", PRIVATE + "\nvalue", PRIVATE + "\rvalue",
    PRIVATE + " value", PRIVATE + "\tvalue", PRIVATE + "\x00", PRIVATE + "\x7f",
    PRIVATE + "\x0b", PRIVATE + "\x0c", PRIVATE + "é", "\u00a0" + PRIVATE,
], ids=["empty", "padding-only", "none", "integer", "bool", "list", "dict", "injection",
        "embedded-lf", "embedded-cr", "embedded-space", "embedded-tab", "nul", "del",
        "vertical-tab", "form-feed", "non-ascii", "non-http-padding"])
def test_invalid_token_never_creates_session(monkeypatch, capsys, token):
    monkeypatch.setattr("requests.Session", lambda: pytest.fail("invalid token created a session"))
    with pytest.raises(PreviewError) as caught:
        read_gist({**ENV, "GITHUB_TOKEN": token}, Budget())
    assert caught.value.payload() == PreviewError("preview_unavailable").payload()
    assert reader_failure_stage(caught.value) == "state_configuration"
    assert failure_code(caught.value) == "preview_error"
    output = capsys.readouterr()
    assert output.out == "" and PRIVATE not in output.err
    assert json.loads(output.err) == {"component": "graphic_preview", "stage": "state_configuration"}


def test_nonstring_token_is_not_stringified(monkeypatch, capsys):
    class Hostile:
        def __str__(self):
            pytest.fail("credential string hook")

    test_invalid_token_never_creates_session(monkeypatch, capsys, Hostile())


@pytest.mark.parametrize("error", [requests.exceptions.InvalidHeader, transport_errors.InvalidHeader])
def test_upstream_header_failure_keeps_fixed_class_and_no_retry(monkeypatch, capsys, error):
    adapter = install(monkeypatch, error(PRIVATE))
    with pytest.raises(PreviewError) as caught:
        read_gist(ENV, Budget())
    assert failure_code(caught.value) == "invalid_header"
    assert reader_failure_stage(caught.value) == "state_metadata_send"
    assert len(adapter.calls) == 1
    assert PRIVATE not in capsys.readouterr().err + str(caught.value)


def test_protected_http_status_uses_normalized_token(status_endpoint, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", ENV["GITHUB_TOKEN"] + "\r\n")
    adapter = install(monkeypatch, wire(metadata()))
    status, _, body = status_endpoint(headers={"Authorization": AUTH})
    assert status == 200 and body == {"schema_version": 1, "state_reader": "available",
        "rendering": "not_evaluated", "source_qualification": "not_evaluated", "publication_approved": False}
    assert len(adapter.calls) == 1
    assert adapter.calls[0][0].headers["Authorization"] == "token fixture-secret"
    assert ENV["GITHUB_TOKEN"] not in json.dumps(body) + capsys.readouterr().err
