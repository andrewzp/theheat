import base64
from email.message import Message

import pytest

from src.dashboard_preview.auth import authorize
from src.dashboard_preview.errors import PreviewError

BASIC = {"DASHBOARD_USERNAME": "editor", "DASHBOARD_PASSWORD": "fixture:secret"}
PROTECTED = {"DASHBOARD_AUTH_DISABLED": "1", "VERCEL": "1", "VERCEL_ENV": "production",
             "VERCEL_URL": "dashboard-generated.vercel.app"}
AUTH = "Basic " + base64.b64encode(b"editor:fixture:secret").decode()


@pytest.mark.parametrize("path", ["/api/graphic_preview", "/api/graphic_preview.py",
                                 "http://localhost:8000/api/graphic_preview"])
def test_basic_and_both_native_paths(path):
    authorize(path, {"Host": "localhost:8000", "Authorization": AUTH,
                     "Origin": "http://localhost:8000"}, BASIC)


def test_outer_protection_is_exact_generated_host_only():
    authorize("https://dashboard-generated.vercel.app/api/graphic_preview",
              {"Host": PROTECTED["VERCEL_URL"], "X-Forwarded-Host": "untrusted.example"}, PROTECTED)


@pytest.mark.parametrize("env,headers,path,code", [
    ({}, {"Host": "localhost"}, "/api/graphic_preview", "preview_unavailable"),
    ({"DASHBOARD_USERNAME": "editor"}, {"Host": "localhost"}, "/api/graphic_preview", "preview_unavailable"),
    (BASIC, {"Host": "localhost"}, "/api/graphic_preview", "authentication_required"),
    (BASIC, {"Host": "localhost", "Authorization": "Basic !!!!!"}, "/api/graphic_preview", "authentication_required"),
    (BASIC, {"Host": "localhost", "Authorization": AUTH, "Origin": "null"}, "/api/graphic_preview", "origin_mismatch"),
    (BASIC, {"Host": "localhost", "Authorization": AUTH}, "http://other.example/api/graphic_preview", "bad_request"),
    (BASIC, {"Host": "localhost", "Authorization": AUTH}, "/api/graphic_preview?private=1", "bad_request"),
    (BASIC, {"Host": "localhost", "Authorization": AUTH}, "//localhost/api/graphic_preview", "bad_request"),
    (BASIC, {"Host": "localhost", "Authorization": AUTH}, "/other", "bad_request"),
    (BASIC, {"Host": "other.example", "Authorization": AUTH}, "/api/graphic_preview", "preview_unavailable"),
    (PROTECTED, {"Host": "alias.vercel.app", "X-Forwarded-Host": PROTECTED["VERCEL_URL"]}, "/api/graphic_preview", "sign_in_required"),
    (PROTECTED, {"X-Forwarded-Host": PROTECTED["VERCEL_URL"]}, "/api/graphic_preview", "authentication_required"),
    ({**PROTECTED, "VERCEL": "0"}, {"Host": PROTECTED["VERCEL_URL"]}, "/api/graphic_preview", "preview_unavailable"),
    ({**PROTECTED, "VERCEL_URL": "evil.example"}, {"Host": "evil.example"}, "/api/graphic_preview", "preview_unavailable"),
    (PROTECTED, {"Host": PROTECTED["VERCEL_URL"]}, "https://alias.vercel.app/api/graphic_preview", "bad_request"),
    (PROTECTED, {"Host": PROTECTED["VERCEL_URL"], "Origin": "https://alias.vercel.app"}, "/api/graphic_preview", "origin_mismatch"),
])
def test_authorization_failure_matrix(env, headers, path, code):
    with pytest.raises(PreviewError) as error:
        authorize(path, headers, env)
    assert error.value.code == code


def test_duplicate_host_and_authorization_rejected():
    for key, value in [("Host", "localhost"), ("Authorization", AUTH)]:
        headers = Message()
        headers["Host"], headers["Authorization"] = "localhost", AUTH
        headers[key] = value
        with pytest.raises(PreviewError, match="Refresh"):
            authorize("/api/graphic_preview", headers, BASIC)
