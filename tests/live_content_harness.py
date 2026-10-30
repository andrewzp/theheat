"""Invented, credential-free boundaries for the live-content journeys (test-only).

Named fake boundaries only, every one recorded:

- HTTP: ``requests.adapters.HTTPAdapter.send`` serves invented Open-Meteo daily
  forecasts, an in-memory Gist and an invented X create endpoint. Any other URL
  is refused; DNS lookups and every socket connection path are refused first.
- Models: the Anthropic and Gemini SDK client factories return the SDKs' own
  response types (``anthropic.types.Message``/``TextBlock`` and
  ``GenerateContentResponse``), so the real writer request/parser, fact-check,
  critic and safety interpreters run unchanged. Each request is routed by its
  production prompt: fact check (JSON schema config), critic (critic system
  prompt) or safety (the safety template). The verdict is the script's.
- Data files: invented city and Meteostat-shaped normals CSV files are read by the
  real loaders.

No credential, network, model, Gist or X access. Inputs are invented; the city
names and coordinates come from the checked-in catalogue so they resolve to
registered places.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import socket
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
X_CREATE = "https://api.twitter.com/2/tweets"
GIST_ID = "0123456789abcdef0123"
INVENTED_TOKEN = "invented-not-a-credential"

# (catalogue city, zone, invented departure in C or a hold kind). Departures are
# invented values; Nairobi has no normal and Sydney's normal is ambiguous.
CITIES = (
    ("Riyadh", "Asia/Riyadh", 9.2), ("Baghdad", "Asia/Baghdad", 8.1), ("Cairo", "Africa/Cairo", 7.4),
    ("Delhi", "Asia/Kolkata", 6.9), ("Karachi", "Asia/Karachi", 6.0), ("Phoenix", "America/Phoenix", 5.5),
    ("Madrid", "Europe/Madrid", 4.8), ("Athens", "Europe/Athens", 4.1), ("Lagos", "Africa/Lagos", 3.3),
    ("Bangkok", "Asia/Bangkok", 2.7), ("Tokyo", "Asia/Tokyo", 2.2), ("Lima", "America/Lima", 1.6),
    ("Nairobi", "Africa/Nairobi", "missing"), ("Sydney", "Australia/Sydney", "ambiguous"),
)
NORMAL_C = 30.0
NORMAL_HEADER = ("city", "country", "lat", "lon", "place_id", "sampling_point_id", "period_start", "period_end",
                 "retrieved_at", "source_product", "month", "avg_high_c")


def catalogue_rows(names) -> list[dict]:
    """Catalogue rows in the requested order (the catalogue's first row per name)."""
    names = list(names)
    with open(ROOT / "data/cities.csv", newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["city"] in set(names)]
    first: dict[str, dict] = {}
    for row in rows:  # The catalogue has a few alias pairs; keep each name's first row.
        first.setdefault(row["city"], row)
    assert set(first) == set(names), sorted(set(names) - set(first))
    return [first[name] for name in names]


def write_catalogue(path: Path, names=None) -> list[dict]:
    rows = catalogue_rows(names or [name for name, _zone, _value in CITIES])
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def normal_rows(month: int, cities=CITIES, *, normal_c: float = NORMAL_C, product: str = "meteostat-normals-point-v1",
                retrieved_at: str = "2026-01-15T00:00:00Z") -> list[dict]:
    """Invented normals for the real loader; one point/month row each, two for an ambiguous city."""
    from src.data import places

    out = []
    for name, _zone, kind in cities:
        if kind == "missing":
            continue
        row = catalogue_rows([name])[0]
        place = places.place_for_row(row)
        base = {"city": row["city"], "country": row["country"], "lat": f"{place['lat']}", "lon": f"{place['lon']}",
                "place_id": place["place_id"], "sampling_point_id": place["sampling_point_id"],
                "period_start": "1991", "period_end": "2020", "retrieved_at": retrieved_at, "source_product": product,
                "month": str(month), "avg_high_c": f"{normal_c}"}
        out.append(base)
        if kind == "ambiguous":
            out.append({**base, "avg_high_c": f"{normal_c + 1.5}"})
    return out


def write_normals(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(NORMAL_HEADER))
        writer.writeheader()
        writer.writerows(rows)


def forecast_table(cities=CITIES, *, normal_c: float = NORMAL_C) -> dict:
    """Coordinate key → invented zone and daily maximum for the Open-Meteo fake."""
    from src.data import places

    table = {}
    for name, zone, kind in cities:
        row = catalogue_rows([name])[0]
        place = places.place_for_row(row)
        departure = kind if isinstance(kind, float) else 3.0
        table[coordinate_key(place["lat"], place["lon"])] = {"zone": zone, "max_c": round(normal_c + departure, 1)}
    return table


def city_temps(now: datetime, cities=CITIES, *, captured: datetime | None = None, day_shift: int = 0) -> list:
    """The real Open-Meteo adapter's evidence from invented payloads, without HTTP."""
    from datetime import date

    from src.data import places
    from src.data.open_meteo import CityTemp
    from src.data.temperature_evidence import forecast_day

    table = forecast_table(cities)
    out = []
    for row in catalogue_rows([name for name, _zone, _kind in cities]):
        place = places.place_for_row(row)
        spec = table[coordinate_key(place["lat"], place["lon"])]
        payload = forecast_payload(place["lat"], place["lon"], zone=spec["zone"], max_c=spec["max_c"], now=now,
                                   day_shift=day_shift)
        stamp = (captured or now).isoformat().replace("+00:00", "Z")
        result = forecast_day(payload, retrieved_at=stamp)
        out.append(CityTemp(row["city"], row["country"], place["lat"], place["lon"], result["max_c"],
                            signal_date=date.fromisoformat(result["valid_date"]), evidence=result["evidence"]))
    return out


def qualified_inputs(directory: Path, now: datetime, cities=CITIES) -> tuple[list[dict], dict, list]:
    """(catalogue cities, the real loader's normals, adapter-shaped forecasts) for ``now``'s month."""
    from src.data import open_meteo

    path = directory / "invented-normals.csv"
    write_normals(path, normal_rows(now.month, cities))
    return (catalogue_rows([name for name, _zone, _kind in cities]), open_meteo.load_normals(str(path)),
            city_temps(now, cities))


def coordinate_key(lat: Any, lon: Any) -> str:
    return f"{float(lat):.4f},{float(lon):.4f}"


def forecast_payload(lat: float, lon: float, *, zone: str, max_c: float, now: datetime, day_shift: int = 0) -> dict:
    local = now.astimezone(ZoneInfo(zone))
    delta = local.utcoffset()
    assert delta is not None
    offset = int(delta.total_seconds())
    return {"latitude": round(lat + 0.02, 3), "longitude": round(lon - 0.03, 3), "elevation": 120.0,
            "generationtime_ms": 0.2, "utc_offset_seconds": offset, "timezone": zone,
            "timezone_abbreviation": local.tzname(),
            "daily_units": {"time": "iso8601", "temperature_2m_max": "°C"},
            "daily": {"time": [(local.date() + timedelta(days=day_shift)).isoformat()], "temperature_2m_max": [max_c]}}


def _reply(request, status: int, body: bytes, headers: dict | None = None):
    import requests
    from requests.structures import CaseInsensitiveDict

    response = requests.models.Response()
    response.status_code, response.url, response.request = status, request.url, request
    response.reason = {200: "OK", 201: "Created"}.get(status, "Invented")
    response.headers = CaseInsensitiveDict({"content-type": "application/json", "content-length": str(len(body)),
                                            **(headers or {})})
    response.raw, response.encoding = io.BytesIO(body), None
    return response


def aq_payload(lat: float, lon: float, day: str, *, pm25: float | None = 40.0, dust: float | None = 100.0,
               pm10: float | None = 60.0, zone: str = "GMT", offset: int = 0, grid=None) -> dict:
    """An invented Open-Meteo air-quality day for one point (grid defaults to the point)."""
    grid = grid or (lat, lon)
    hours = [f"{day}T{hour:02d}:00" for hour in range(24)]
    return {"latitude": grid[0], "longitude": grid[1], "timezone": zone, "utc_offset_seconds": offset,
            "hourly_units": {"pm2_5": "μg/m³", "pm10": "μg/m³", "dust": "μg/m³", "aerosol_optical_depth": "",
                             "us_aqi": "USAQI"},
            "hourly": {"time": hours, "pm2_5": [pm25] * 24, "pm10": [pm10] * 24, "dust": [dust] * 24,
                       "aerosol_optical_depth": [0.6] * 24, "us_aqi": [180] * 24}}


@dataclass
class Transport:
    """One invented HTTP world; ``now`` supplies the forecast's provider-local day."""

    forecasts: dict = field(default_factory=dict)
    air_quality: dict = field(default_factory=dict)  # coordinate key → aq_payload keyword overrides
    air_quality_after: dict | None = None  # A changed source served after ``aq_switch_after`` requests.
    aq_switch_after: int | None = None
    aq_failure: str | None = None
    aq_calls: list = field(default_factory=list)
    gist: dict = field(default_factory=dict)
    gist_id: str = GIST_ID
    x_failure: str | None = None
    day_shift: int = 0
    calls: list = field(default_factory=list)
    x_posts: list = field(default_factory=list)
    gist_patches: int = 0
    now: Callable[[], datetime] = field(default=lambda: datetime.now().astimezone())

    def send(self, _adapter, request, **_options):
        url, method = request.url, request.method
        parts = urlsplit(url)
        self.calls.append([method, f"{parts.scheme}://{parts.netloc}{parts.path}"])
        if f"{parts.scheme}://{parts.netloc}{parts.path}" == FORECAST_URL and method == "GET":
            query = {key: values[0] for key, values in parse_qs(parts.query).items()}
            assert query["daily"] == "temperature_2m_max" and query["timezone"] == "auto"
            spec = self.forecasts.get(coordinate_key(query["latitude"], query["longitude"]))
            if spec is None:
                return _reply(request, 400, b'{"error":true,"reason":"invented: no forecast"}')
            payload = forecast_payload(float(query["latitude"]), float(query["longitude"]), zone=spec["zone"],
                                       max_c=spec["max_c"], now=self.now(), day_shift=spec.get("day_shift", self.day_shift))
            return _reply(request, 200, json.dumps(payload).encode())
        if f"{parts.scheme}://{parts.netloc}{parts.path}" == AQ_URL and method == "GET":
            query = {key: values[0] for key, values in parse_qs(parts.query).items()}
            assert query["start_date"] == query["end_date"] and query["timezone"] == "auto" and query["domains"] == "auto"
            points = list(zip(query["latitude"].split(","), query["longitude"].split(","), strict=True))
            self.aq_calls.append({"points": len(points), "day": query["start_date"]})
            if self.aq_failure == "unavailable":
                import requests
                raise requests.ConnectionError("invented air-quality outage")
            switched = self.aq_switch_after is not None and len(self.aq_calls) > self.aq_switch_after
            table = self.air_quality_after if switched and self.air_quality_after is not None else self.air_quality
            rows = [aq_payload(float(lat), float(lon), query["start_date"],
                               **table.get(coordinate_key(lat, lon), {})) for lat, lon in points]
            body = json.dumps(rows[0] if len(rows) == 1 else rows).encode()
            if self.aq_failure == "oversize":
                body = body + b" " * 70_000
            return _reply(request, 200, body)
        if url == f"https://api.github.com/gists/{self.gist_id}":
            if method == "GET":
                files = {name: {"content": content, "truncated": False} for name, content in sorted(self.gist.items())}
                return _reply(request, 200, json.dumps({"files": files}).encode())
            assert method == "PATCH"
            for name, value in json.loads(request.body)["files"].items():
                self.gist[name] = value["content"]
            self.gist_patches += 1
            return _reply(request, 200, b"{}")
        if url == X_CREATE and method == "POST":
            import requests

            text = json.loads(request.body)["text"]
            self.x_posts.append(text)
            if self.x_failure == "create_lost":
                raise requests.ConnectionError("invented create response lost")
            return _reply(request, 201, json.dumps({"data": {"id": f"invented-x-{len(self.x_posts)}", "text": text}}).encode())
        raise AssertionError(f"unallowed invented-transport request: {method} {url}")

    def install(self, setattr_: Callable) -> None:
        import requests

        def send(adapter, request, **options):  # A plain function: bound per adapter instance.
            return self.send(adapter, request, **options)

        setattr_(requests.adapters.HTTPAdapter, "send", send)
        # OFFLINE-only owned-process seam (as in the NHC fixture). The real
        # fixed request, parser and current-source comparison still run here.
        from src.data import air_quality_current
        setattr_(air_quality_current, "_http_get", air_quality_current._http_get_inprocess)
        trap_network(setattr_)


def _refuse(*_args, **_kwargs):
    raise AssertionError("external connection trapped")


def trap_network(setattr_: Callable) -> None:
    """Refuse DNS and every socket connection path before any lookup or connect."""
    for owner, name in ((socket, "getaddrinfo"), (socket, "gethostbyname"), (socket, "create_connection"),
                        (socket.socket, "connect"), (socket.socket, "connect_ex")):
        setattr_(owner, name, _refuse)


@dataclass
class ModelScript:
    """The invented model answers; each verdict is explicit, never inferred from copy."""

    copy: str = ""
    copies: dict = field(default_factory=dict)  # signal_kind → copy, when one run writes several kinds
    writer_kill: str | None = None
    fact_passed: bool = True
    critic: dict = field(default_factory=lambda: {"verdict": "PASS", "kill_reason": None, "revise_instruction": None,
                                                  "selected_index": None})
    safety: str = "NO"
    requests: list = field(default_factory=list)

    def writer_json(self, request: dict | None = None) -> str:
        copy = self.copy
        prompt = json.dumps(request.get("messages")) if request else ""
        for kind, kind_copy in self.copies.items():
            if f'\\"signal_kind\\": \\"{kind}\\"' in prompt:
                copy = kind_copy
        if self.writer_kill:
            return json.dumps({"tweet": None, "kill_reason": self.writer_kill, "angle_chosen": "", "era_anchor_used": None,
                               "peer_comparison_used": None, "reasoning": "Invented offline decline.",
                               "cited_impact": None, "kill_scope": "style", "kill_code": None})
        return json.dumps({"tweet": copy, "kill_reason": None, "angle_chosen": "forecast_departure",
                           "era_anchor_used": None, "peer_comparison_used": None,
                           "reasoning": "Invented offline writer response.", "cited_impact": None,
                           "kill_scope": None, "kill_code": None})

    def google_text(self, request: dict) -> tuple[str, str]:
        from src.two_bot.prompts.critic_prompt import CRITIC_SYSTEM_PROMPT

        config = request.get("config")
        schema = getattr(config, "response_json_schema", None) if config is not None else None
        if isinstance(config, dict):
            schema = config.get("response_json_schema")
        contents = str(request.get("contents") or "")
        if schema is not None:
            tweet = _between(contents)
            claims = [{"text": tweet, "kind": "comparison"}] if tweet else []
            body = {"passed": self.fact_passed, "failures": [] if self.fact_passed else ["invented: unsupported"],
                    "extracted_claims": claims}
            return "fact_check", json.dumps(body)
        if contents.startswith(CRITIC_SYSTEM_PROMPT):
            return "critic", json.dumps(self.critic)
        return "safety", self.safety

    def install(self, setattr_: Callable) -> None:
        import anthropic
        from google import genai

        script = self
        # Build each SDK type's validator now: a frozen clock (freezegun) replaces
        # datetime, and pydantic cannot generate a schema for the substitute.
        _sdk_message(script.writer_json(), "invented-warmup")
        _sdk_response("NO")

        class _Messages:
            def create(self, **request):
                script.requests.append(("writer", request))
                return _sdk_message(script.writer_json(request), request["model"])

        class _Anthropic:
            def __init__(self, *_args, **_kwargs):
                self.messages = _Messages()

        class _Models:
            def generate_content(self, **request):
                stage, text = script.google_text(request)
                script.requests.append((stage, request))
                return _sdk_response(text)

        class _Client:
            def __init__(self, *_args, **_kwargs):
                self.models = _Models()

            def close(self):
                return None

        setattr_(anthropic, "Anthropic", _Anthropic)
        setattr_(genai, "Client", _Client)

    def stages(self) -> list[str]:
        return [stage for stage, _request in self.requests]


def _sdk_message(text: str, model: str):
    from anthropic.types import Message, TextBlock, Usage

    return Message(id="msg_invented", type="message", role="assistant", model=model,
                   content=[TextBlock(type="text", text=text)], stop_reason="end_turn", stop_sequence=None,
                   usage=Usage(input_tokens=2000, output_tokens=120))


def _sdk_response(text: str):
    from google.genai import types as genai_types

    return genai_types.GenerateContentResponse(
        candidates=[genai_types.Candidate(content=genai_types.Content(role="model", parts=[genai_types.Part(text=text)]),
                                          finish_reason=genai_types.FinishReason.STOP)],
        usage_metadata=genai_types.GenerateContentResponseUsageMetadata(
            prompt_token_count=900, candidates_token_count=40, total_token_count=940))


def _between(contents: str) -> str:
    """The checked tweet as the production fact-check prompt quotes it."""
    from src.two_bot.prompts.fact_check_prompt import FACT_CHECK_USER_PROMPT_TEMPLATE

    head = FACT_CHECK_USER_PROMPT_TEMPLATE.split("{tweet}")[0]
    tail = FACT_CHECK_USER_PROMPT_TEMPLATE.split("{tweet}")[1].split("{", 1)[0]
    start = contents.rfind(head)
    if start < 0:
        return ""
    start += len(head)
    end = contents.find(tail, start) if tail else -1
    return contents[start:end] if end >= 0 else ""


def install_hot10_world(tmp_path: Path, monkeypatch, *, copy: str):
    """In-process Hot10 world: invented catalogue/normals files read by the real loaders,
    the invented HTTP world, the model script and a CandidateBudget.settle recorder.

    The caller freezes time. Returns a namespace with transport, script, settled
    and normals_csv.
    """
    from copy import deepcopy
    from datetime import UTC
    from types import SimpleNamespace

    from src.data import open_meteo
    from src.orchestrator import candidate_budget
    from src.state import DEFAULT_STATE
    from src.voice import safety

    cities_csv, normals_csv = tmp_path / "cities.csv", tmp_path / "normals.csv"
    write_catalogue(cities_csv)
    write_normals(normals_csv, normal_rows(10))
    monkeypatch.setattr(open_meteo.load_cities, "__defaults__", (str(cities_csv),))
    monkeypatch.setattr(open_meteo.load_normals, "__defaults__", (str(normals_csv),))
    transport = Transport(forecasts=forecast_table(), gist={"state.json": json.dumps(deepcopy(DEFAULT_STATE))},
                          now=lambda: datetime.now(UTC))
    transport.install(monkeypatch.setattr)
    script = ModelScript(copy=copy)
    script.install(monkeypatch.setattr)
    for name, value in MODEL_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", INVENTED_TOKEN)
    monkeypatch.setattr(safety, "_SAFETY_CACHE", type(safety._SAFETY_CACHE)())  # No reuse across tests.
    monkeypatch.setattr("src.state.GIST_ID", GIST_ID)
    monkeypatch.setattr("src.state.GITHUB_TOKEN", INVENTED_TOKEN)
    monkeypatch.setattr("src.data._http.time.sleep", lambda _s: None, raising=False)
    settled: list = []
    real_settle = candidate_budget.CandidateBudget.settle

    def settle(self, key, *, writer_started):
        settled.append((self.operation, key, writer_started))
        return real_settle(self, key, writer_started=writer_started)
    monkeypatch.setattr(candidate_budget.CandidateBudget, "settle", settle)
    return SimpleNamespace(transport=transport, script=script, settled=settled, normals_csv=normals_csv, tmp=tmp_path)


MODEL_ENV = {"ANTHROPIC_API_KEY": INVENTED_TOKEN, "GEMINI_API_KEY": INVENTED_TOKEN,
             "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0"}
# Invented values so the real X adapter builds its client; requests reach only the fake transport.
X_ENV = {"TWITTER_API_KEY": "invented", "TWITTER_API_SECRET": "invented", "TWITTER_ACCESS_TOKEN": "invented",
         "TWITTER_ACCESS_SECRET": "invented"}


__all__ = ["AQ_URL", "CITIES", "aq_payload", "trap_network", "FORECAST_URL", "GIST_ID", "MODEL_ENV", "X_ENV", "ModelScript", "NORMAL_C", "Transport", "X_CREATE",
           "catalogue_rows", "city_temps", "coordinate_key", "install_hot10_world", "qualified_inputs", "forecast_payload", "forecast_table", "normal_rows", "write_catalogue",
           "write_normals"]
