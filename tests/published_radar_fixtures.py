"""Explicitly invented radar/source data. No real specimen or source fetch."""

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path

from PIL import Image, ImageDraw
import responses

from src.commands.schema import utc_text
from src.data import nws_alerts, _freshness
from src.media import published_radar as r
from src.two_bot.intern.disasters import build_severe_weather_bundle

AT = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)


def feature(at=AT):
    day = at.date().isoformat()
    return {
        "type": "Feature",
        "id": "https://api.weather.gov/alerts/invented-radar-case",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-97.8, 35.2], [-97.2, 35.2], [-97.2, 35.8], [-97.8, 35.8], [-97.8, 35.2]]
            ],
        },
        "properties": {
            "id": "invented-radar-case",
            "event": "Tornado Warning",
            "status": "Actual",
            "category": "Met",
            "messageType": "Alert",
            "severity": "Extreme",
            "areaDesc": "Oklahoma, OK; Cleveland, OK; Canadian, OK",
            "headline": "INVENTED: catastrophic tornado warning category",
            "description": "Invented test warning; no actual weather claim.",
            "instruction": "Invented fixture only.",
            "senderName": "NWS Invented Test Office",
            "sent": f"{day}T06:58:00-05:00",
            "effective": f"{day}T06:58:00-05:00",
            "onset": f"{day}T06:58:00-05:00",
            "expires": f"{day}T07:45:00-05:00",
            "ends": f"{day}T07:30:00-05:00",
            "references": [],
            "parameters": {
                "tornadoDamageThreat": ["CATASTROPHIC"],
                "tornadoDetection": ["OBSERVED"],
            },
        },
    }


def parsed(monkeypatch, item=None, *, at=AT):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at

    class Day(_freshness.date):
        @classmethod
        def today(cls):
            return at.date()

    monkeypatch.setattr(nws_alerts, "datetime", Clock)
    monkeypatch.setattr(_freshness, "date", Day)
    with responses.RequestsMock() as calls:
        calls.add(responses.GET, r.ALERT_URL, json={"features": [item or feature(at)]}, status=200)
        alerts = nws_alerts.fetch_alerts(strict=True)
        assert len(calls.calls) == 1 and "message_type=alert%2Cupdate" in calls.calls[0].request.url
    return alerts


def bundle(monkeypatch, *, at=AT):
    return build_severe_weather_bundle(parsed(monkeypatch, at=at)[0])


def input_document(*, at=AT):
    minute = at - timedelta(minutes=1)
    literal = minute.strftime("%m/%d/%Y %H:%M UTC (06:59 CDT)")
    frame = Image.new("P", (600, 550), 0)
    frame.putpalette([15, 35, 65, 240, 210, 30, 230, 60, 40, 45, 170, 100] + [0] * 756)
    draw = ImageDraw.Draw(frame)
    draw.rectangle((150, 120, 400, 360), fill=2)
    draw.text((15, 15), "INVENTED OFFLINE FIXTURE - KTLX - NOT ACTUAL WEATHER", fill=1)
    draw.text((15, 45), literal, fill=1)
    draw.text((190, 200), "Oklahoma City", fill=1)
    draw.text((15, 490), "NATIONAL WEATHER SERVICE - INVENTED LABEL FIXTURE", fill=1)
    output = io.BytesIO()
    frame.save(output, format="GIF")
    raw = output.getvalue()
    references = {
        "product": b"Invented retained product-reference fixture; not official source truth.",
        "reuse": b"Invented retained reuse-reference fixture; not a rights verdict.",
    }
    receipt = b"Invented local acquisition receipt; no network request."
    registry = Path(__file__).resolve().parents[1] / "data/place_registry.json"
    doc = dict(
        schema_version=1,
        family=r.FAMILY,
        station="KTLX",
        source_url=r.SOURCE_URL,
        original=dict(
            sha256=r.digest(raw),
            byte_count=len(raw),
            mime_type="image/gif",
            width=600,
            height=550,
            frame_count=1,
        ),
        retrieved_at=utc_text(at),
        receipt=dict(sha256=r.digest(receipt), byte_count=len(receipt)),
        metadata=dict(
            time_literal=literal,
            frame_minute_utc=utc_text(minute),
            precision="minute",
            issued_utc=None,
            subtype=None,
            elevation_degrees=None,
            product="station reflectivity",
            units="dBZ",
            reflectivity_legend=r.SCALE,
            warning_legend=r.LEGEND,
            marks=["NOAA logo", "NWS logo"],
            credit="NATIONAL WEATHER SERVICE",
            point=dict(
                place_id="pl0406",
                label="Oklahoma City",
                registry_sha256=r.digest(registry.read_bytes()),
            ),
        ),
        references={
            k: dict(
                url=r.PRODUCT_URL if k == "product" else r.REUSE_URL,
                sha256=r.digest(v),
                byte_count=len(v),
            )
            for k, v in references.items()
        },
        synthetic=True,
        metadata_status="unreviewed",
    )
    return doc, raw, references, receipt


def spec(monkeypatch):
    doc, raw, refs, receipt = input_document()
    value = r.make_spec(
        bundle(monkeypatch).to_dict(),
        doc,
        source_origin=dict(
            namespace="draft-source-origin-v1", snapshot_id="a" * 64, canonical_sha256="b" * 64
        ),
        registry_sha256=doc["metadata"]["point"]["registry_sha256"],
        point=r.POINT,
        selection_sha256="c" * 64,
        now=AT,
    )
    return value, raw
