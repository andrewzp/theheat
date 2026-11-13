"""One nominated, completed-month C3S finding; no annual projections or fallback.

This is an attributed publisher report based on ERA5 retrospective analysis,
not a new measurement, an independently reconstructed global record or a forecast.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
import re

PRODUCT = "copernicus-c3s-monthly-temperature-report-v1"
KIND = "monthly_climate_report"
FINDING_KEYS = frozenset({"report_month", "period_start", "period_end", "rank", "surface_temperature_c",
    "anomaly_1991_2020_c", "anomaly_1850_1900_c", "publisher", "source_url", "source_product", "evidence_type", "basis"})
REPORT_KEYS = FINDING_KEYS | {"finding_sha256", "retrieved_at", "response_sha256"}
MONTHS = ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
MAX_BODY = 1_048_576


class ReportHeld(ValueError):
    pass


def report_period(month: str, now: datetime) -> tuple[str, date, date]:
    if not isinstance(month, str) or not re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", month):
        raise ReportHeld("c3s_period_invalid")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ReportHeld("c3s_clock_invalid")
    previous = now.astimezone(UTC).date().replace(day=1) - timedelta(days=1)
    if month != previous.strftime("%Y-%m"):
        raise ReportHeld("c3s_requires_previous_completed_month")
    start = date.fromisoformat(month + "-01")
    url = f"https://climate.copernicus.eu/surface-air-temperature-{MONTHS[start.month].lower()}-{start.year}"
    return url, start, previous


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.article_parts: list[str] = []
        self.rows: list[str] = []
        self.li_parts: list[str] = []
        self.li_depth = 0
        self.in_main = False
        self.main_count = 0
        self.hidden = 0
        self.quote = 0
        self.depth = 0
        self.finished = False

    def handle_starttag(self, tag, attrs):
        if tag == "main" and dict(attrs).get("id") == "maincontent":
            self.main_count += 1
            self.in_main = True
        if tag == "article" and self.in_main and not self.finished:
            self.depth += 1
        if tag == "li" and self.depth:
            self.li_depth += 1
            if self.li_depth == 1:
                self.li_parts = []
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "blockquote":
            self.quote += 1

    def handle_endtag(self, tag):
        if tag == "li" and self.li_depth:
            if self.li_depth == 1:
                self.rows.append(" ".join(" ".join(self.li_parts).split()))
            self.li_depth -= 1
        if tag == "article" and self.depth:
            self.depth -= 1
            self.finished = self.depth == 0
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag == "blockquote" and self.quote:
            self.quote -= 1
        if tag == "main":
            self.in_main = False

    def handle_data(self, data):
        if self.in_main and not self.hidden:
            self.article_parts.append(data)
            if self.depth and not self.quote:
                self.parts.append(data)
                if self.li_depth == 1:
                    self.li_parts.append(data)


def parse_report(raw: bytes, month: str, *, now: datetime) -> dict:
    url, start, end = report_period(month, now)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY:
        raise ReportHeld("c3s_body_bound")
    try:
        parser = _Text()
        parser.feed(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ReportHeld("c3s_body_invalid") from None
    if parser.main_count != 1:
        raise ReportHeld("c3s_primary_article_missing_or_ambiguous")
    if re.search(r"\b(?:correction|retraction)\b", " ".join(parser.article_parts), re.I):
        raise ReportHeld("c3s_source_has_correction")
    period = f"{MONTHS[start.month]} {start.year}"
    number = r"([0-9]{1,2}(?:\.[0-9]{1,3})?)"
    degree = r"\s*°\s*C"
    # The named past month and actual record statement are mandatory. A future
    # annual outlook, chart caption or unrelated percentage cannot satisfy this.
    first_pattern = re.escape(period) + r" was the warmest " + re.escape(MONTHS[start.month]) \
        + r" globally\s*, with an average surface air temperature of " + number + degree
    first_pattern += r", " + number + degree + r" above the 1991[–-]2020 average for the month"
    second_pattern = re.escape(period) + r" was " + number + degree \
        + r" above the estimated 1850[–-]1900 pre-industrial average for the month"
    first = [match.groups() for row in parser.rows if (match := re.match(first_pattern, row))]
    second = [match.group(1) for row in parser.rows if (match := re.match(second_pattern, row))]
    if len(set(first)) != 1 or len(set(second)) != 1:
        raise ReportHeld("c3s_monthly_finding_missing_or_conflicting")
    absolute, recent = map(float, first[0])
    preindustrial = float(second[0])
    if not (-20 < absolute < 40 and 0 < recent < 5 and 0 < preindustrial < 5):
        raise ReportHeld("c3s_value_invalid")
    finding = {"report_month": month, "period_start": start.isoformat(), "period_end": end.isoformat(),
        "rank": "warmest month-of-year in the publisher's ERA5 record", "surface_temperature_c": absolute,
        "anomaly_1991_2020_c": recent, "anomaly_1850_1900_c": preindustrial,
        "publisher": "Copernicus Climate Change Service (C3S/ECMWF)", "source_url": url,
        "source_product": PRODUCT, "evidence_type": "retrospective_publisher_report",
        "basis": "ERA5 retrospective analysis; not a weather forecast or a new station measurement"}
    fingerprint = sha256(json.dumps(finding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**finding, "finding_sha256": fingerprint,
            "retrieved_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "response_sha256": sha256(raw).hexdigest()}


def fetch_report(month: str, *, now: datetime | None = None) -> dict:
    import requests
    now = now or datetime.now(UTC)
    url, _, _ = report_period(month, now)
    try:
        # One physical GET, fixed HTTPS host/path, no redirects or transport retry.
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, timeout=10, allow_redirects=False, stream=True,
                             headers={"User-Agent": "theheat-bot (contact@theheat.app)"}) as response:
                if response.status_code != 200:
                    raise ReportHeld("c3s_source_unavailable")
                body = bytearray()
                for part in response.iter_content(8192):
                    if len(body) + len(part) > MAX_BODY:
                        raise ReportHeld("c3s_body_bound")
                    body.extend(part)
        return parse_report(bytes(body), month, now=datetime.now(UTC))
    except requests.RequestException:
        raise ReportHeld("c3s_source_unavailable") from None


def build_bundle(report: dict):
    from src.two_bot.types import StoryBundle
    facts = [{"label": key, "value": report[key]} for key in (
        "report_month", "period_start", "period_end", "rank", "surface_temperature_c",
        "anomaly_1991_2020_c", "anomaly_1850_1900_c", "publisher", "source_url", "source_product", "basis")]
    facts.append({"label": "claim_limit", "value":
        "Attribute the published monthly finding to Copernicus. No annual prediction, projected impact, "
        "permanent Paris-limit breach, independent global reconstruction or station-record claim is supplied."})
    facts.append({"label": "public_source_url", "value": report["source_url"]})
    return StoryBundle(signal_kind=KIND, where="Global", when=report["period_end"],
        event_id="c3s_monthly_" + report["report_month"],
        headline_metric={"label": "reported_monthly_anomaly_preindustrial_c", "value": report["anomaly_1850_1900_c"], "unit": "C"},
        current_facts=facts,
        historical_context={"record_scope": "Publisher's ERA5 global month-of-year record",
                            "preindustrial_reference": "1850-1900", "recent_reference": "1991-2020"},
        raw_signal_dump=dict(report))


def validate_bundle(bundle, *, now: datetime | None = None) -> dict:
    from src.two_bot.types import StoryBundle
    now = now or datetime.now(UTC)
    value = bundle.to_dict() if isinstance(bundle, StoryBundle) else bundle
    if not isinstance(value, dict) or value.get("signal_kind") != KIND:
        raise ReportHeld("c3s_bundle_invalid")
    report = value.get("raw_signal_dump")
    if not isinstance(report, dict) or set(report) != REPORT_KEYS:
        raise ReportHeld("c3s_report_invalid")
    url, start, end = report_period(report["report_month"], now)
    if (report["source_url"] != url or report["source_product"] != PRODUCT
            or report["evidence_type"] != "retrospective_publisher_report"
            or report["period_start"] != start.isoformat() or report["period_end"] != end.isoformat()
            or report["rank"] != "warmest month-of-year in the publisher's ERA5 record"
            or report["publisher"] != "Copernicus Climate Change Service (C3S/ECMWF)"
            or report["basis"] != "ERA5 retrospective analysis; not a weather forecast or a new station measurement"):
        raise ReportHeld("c3s_report_invalid")
    for name, low, high in (("surface_temperature_c", -20, 40), ("anomaly_1991_2020_c", 0, 5), ("anomaly_1850_1900_c", 0, 5)):
        if type(report[name]) not in (int, float) or not low < report[name] < high:
            raise ReportHeld("c3s_value_invalid")
    for name in ("finding_sha256", "response_sha256"):
        if not isinstance(report[name], str) or not re.fullmatch(r"[0-9a-f]{64}", report[name]):
            raise ReportHeld("c3s_report_invalid")
    try:
        captured = datetime.fromisoformat(report["retrieved_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise ReportHeld("c3s_time_invalid") from None
    if captured.tzinfo is None or not timedelta(0) <= now - captured <= timedelta(days=7):
        raise ReportHeld("c3s_time_invalid")
    core = {key: report[key] for key in FINDING_KEYS}
    if sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != report["finding_sha256"]:
        raise ReportHeld("c3s_finding_binding_invalid")
    if value != build_bundle(report).to_dict():
        raise ReportHeld("c3s_bundle_changed")
    return report


def bundle_failures(bundle) -> list[str]:
    raw = getattr(bundle, "raw_signal_dump", None)
    if getattr(bundle, "signal_kind", None) != KIND and not (isinstance(raw, dict) and raw.get("source_product") == PRODUCT):
        return []
    try:
        validate_bundle(bundle)
    except (ValueError, TypeError, KeyError):
        return ["c3s_retained_finding_invalid"]
    return []


def current_bundle_hold(bundle, *, live: bool, now: datetime | None = None) -> str | None:
    now = now or datetime.now(UTC)
    try:
        report = validate_bundle(bundle, now=now)
        if live and fetch_report(report["report_month"], now=now)["finding_sha256"] != report["finding_sha256"]:
            return "c3s_monthly_finding_changed"
    except (KeyError, TypeError, ValueError):
        return "c3s_current_source_unavailable"
    return None


def current_draft_hold(draft: dict, *, live: bool = True, now: datetime | None = None) -> str | None:
    review = draft.get("review_context")
    two_bot = review.get("two_bot") if isinstance(review, dict) else None
    bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    raw = bundle.get("raw_signal_dump") if isinstance(bundle, dict) else None
    governed = draft.get("type") == KIND or (isinstance(bundle, dict) and bundle.get("signal_kind") == KIND) \
        or (isinstance(raw, dict) and raw.get("source_product") == PRODUCT)
    if not governed:
        return None
    from src.editorial.observed_scope import enabled
    if not enabled():
        return "c3s_observed_mode_disabled"
    if draft.get("type") != KIND:
        return "c3s_kind_changed"
    try:
        retained = draft["review_context"]["two_bot"]["bundle"]
        return current_bundle_hold(retained, live=live, now=now)
    except (KeyError, TypeError, ValueError):
        return "c3s_current_source_unavailable"
    return None
