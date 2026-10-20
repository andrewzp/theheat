"""Bounded Gist reads only; no bootstrap, retries, fallback store or source requests."""

import json
import math
import re
import time
from urllib.parse import urlsplit

import requests

from src.dashboard_preview.errors import PreviewError, log_unavailable

STATE_LIMIT = 8 * 1024 * 1024
API_LIMIT = 12 * 1024 * 1024


class Budget:
    def __init__(self, seconds=25, clock=time.monotonic):
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise PreviewError("preview_unavailable")
        return remaining


def strict_json(raw, limit, *, code="preview_unavailable"):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def invalid(_):
        raise ValueError

    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
            raise ValueError
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs, parse_constant=invalid)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                raise ValueError
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError
            if isinstance(item, str):
                item.encode("utf-8")
            elif isinstance(item, dict):
                pending.extend((v, depth + 1) for v in item.values())
                pending.extend((k, depth + 1) for k in item)
            elif isinstance(item, list):
                pending.extend((v, depth + 1) for v in item)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise PreviewError(code) from exc


def _body(session, url, headers, limit, budget, *, diagnostic_stage="state_metadata_http"):
    remaining = budget.remaining()
    with session.get(url, headers=headers, stream=True, allow_redirects=False,
                     timeout=(min(2, remaining), min(3, remaining))) as response:
        if response.status_code != 200:
            log_unavailable(diagnostic_stage, http_status=response.status_code)
            raise PreviewError("preview_unavailable")
        # read1 yields available data rather than waiting to fill a 64KiB chunk.
        # The application checks its budget between reads; Vercel also bounds the
        # complete function to 30s, including DNS/header or native-library stalls.
        response.raw.decode_content = True
        output = bytearray()
        while True:
            budget.remaining()
            part = response.raw.read1(min(65536, limit + 1 - len(output)))
            budget.remaining()
            if not part:
                return bytes(output)
            output.extend(part)
            if len(output) > limit:
                raise PreviewError("preview_unavailable")


def read_gist(env, budget):
    backend = env.get("THEHEAT_STATE_BACKEND", "").strip().lower()
    backend = backend or ("sqlite" if env.get("THEHEAT_DB_PATH") else "gist")
    gist_id, token = env.get("GIST_ID", ""), env.get("GITHUB_TOKEN", "")
    if backend != "gist" or not re.fullmatch(r"[0-9a-f]{20,64}", gist_id) or not token:
        log_unavailable("state_configuration")
        raise PreviewError("preview_unavailable")
    stage = "state_metadata_read"
    try:
        with requests.Session() as session:
            session.trust_env = False
            headers = {"Accept": "application/vnd.github+json", "Authorization": f"token {token}",
                       "Cache-Control": "no-cache"}
            gist = strict_json(_body(session, f"https://api.github.com/gists/{gist_id}", headers, API_LIMIT, budget), API_LIMIT)
            stage = "state_metadata_shape"
            if gist.get("id") != gist_id:
                raise PreviewError("preview_unavailable")
            file = gist["files"]["state.json"]
            if type(file.get("truncated")) is not bool or file.get("filename") != "state.json":
                raise PreviewError("preview_unavailable")
            if file["truncated"]:
                url = file["raw_url"]
                parsed = urlsplit(url)
                path = rf"/[A-Za-z0-9-]+/{gist_id}/raw/[0-9a-f]{{40}}/state\.json"
                if (parsed.scheme != "https" or parsed.netloc != "gist.githubusercontent.com"
                        or not re.fullmatch(path, parsed.path) or parsed.query or parsed.fragment):
                    raise PreviewError("preview_unavailable")
                # Raw secret-Gist URLs need no token; credentials stay at api.github.com.
                stage = "state_raw_read"
                body = _body(session, url, {"Cache-Control": "no-cache"}, STATE_LIMIT, budget,
                             diagnostic_stage="state_raw_http")
            else:
                body = file["content"].encode("utf-8")
            stage = "state_json"
            state = strict_json(body, STATE_LIMIT)
            budget.remaining()
            return state
    except PreviewError:
        log_unavailable(stage)
        raise
    except Exception as exc:
        log_unavailable(stage)
        raise PreviewError("preview_unavailable") from exc
