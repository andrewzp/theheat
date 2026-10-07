"""Entirely invented source packets, never captured NOAA readings or source text."""

from datetime import UTC, datetime, timedelta
import hashlib

from src.data import coral_dhw
from src.data import coral_regional_contract as contract


def packet(dhw=8.25, baa=3, *, region_id="invented_reef", name="Invented Reef", day=None):
    day = day or (datetime.now(UTC).date() - timedelta(days=1))
    index = (
        f"<html><p>Version 3.1</p><p>Latest Data Date: {day:%b}. {day.day}, {day.year}</p>"
        f'<table><tr><td><a href="timeseries/invented.php#{region_id}">{name}</a></td>'
        f'<td><a href="gauges/{region_id}.php">{contract.LABELS[baa]}</a></td>'
        f'<td><a href="data/{region_id}.txt">txt</a></td></tr></table></html>'
    ).encode()
    head = (
        f"Name:\n{name}\n \nPolygon Middle Longitude:\n151.1250\n \n"
        "Polygon Middle Latitude:\n-21.7500\n \nAveraged Maximum Monthly Mean:\n28.1250\n \n"
        "Averaged Monthly Mean (Jan-Dec):\n26 27 28 29 28 27 26 25 24 25 26 27\n \n"
        "First Valid DHW Date:\n2001 25 03\n \nFirst Valid BAA Date:\n2001 31 03\n \n"
        + " ".join(contract.COLUMNS)
        + "\n"
    )
    # Full invented history is local only; production fetches two small ranges.
    rows = []
    for offset in range(199, -1, -1):
        d = day - timedelta(days=offset)
        rows.append(f"{d:%Y %m %d} 26.0000 31.0000 29.5000 1.0000 1.5000 {dhw:.4f} {baa}\n")
    full = (head + "".join(rows)).encode()
    url = contract.DATA_BASE + region_id + ".txt"
    return {
        "index": index,
        "header": full[:2049],
        "tail": full[-8192:],
        "total": len(full),
        "url": url,
        "etag": '"invented-representation-1"',
    }


def range_headers(p, kind):
    start, end = (0, 2048) if kind == "header" else (p["total"] - 8192, p["total"] - 1)
    return {
        "ETag": p["etag"],
        "Content-Range": f"bytes {start}-{end}/{p['total']}",
        "Content-Length": str(end - start + 1),
        "Content-Encoding": "identity",
        "Content-Type": "text/plain",
    }


def receipts(p):
    at = contract.now_utc()
    stations, index = contract.decode_index(p["index"], retrieved_at=at, max_age_days=5)
    values = []
    for kind in ["tail", "header"]:
        r = contract.response_range(
            206, range_headers(p, kind), kind=kind, prior=values[0] if values else None
        )
        values.append(
            {
                **r,
                "source_url": p["url"],
                "response_bytes": len(p[kind]),
                "response_sha256": hashlib.sha256(p[kind]).hexdigest(),
                "retrieved_at": at,
            }
        )
    return stations[0], index, values[1], values[0]


def reading(dhw=8.25, baa=3, **kwargs):
    p = packet(dhw, baa, **kwargs)
    station, index, header, tail = receipts(p)
    receipt = contract.decode_station(
        station, index, p["header"], header, p["tail"], tail, max_age_days=5
    )
    return coral_dhw.CoralDHWReading(
        station.region_id,
        station.region_full_name,
        receipt["valid_date"],
        receipt["dhw_value"],
        station.stress_level,
        baa,
        -21.75,
        151.125,
        provenance=receipt,
    )


def bundle(dhw=8.25, baa=3):
    from src.two_bot.intern.marine import build_coral_bleaching_bundle

    return build_coral_bleaching_bundle(coral_dhw.detect_dhw_thresholds([reading(dhw, baa)])[0])


class Response:
    def __init__(self, body, status=206, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}
        self.closed = False
        self.consumed = 0

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            chunk = self.body[start : start + size]
            self.consumed += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


def install_transport(monkeypatch, p):
    responses, calls = [], []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url == contract.INDEX_URL:
            response = Response(p["index"], 200)
        else:
            assert url == p["url"]
            kind = "tail" if kwargs["headers"]["Range"] == "bytes=-8192" else "header"
            response = Response(p[kind], headers=range_headers(p, kind))
        responses.append(response)
        return response

    monkeypatch.setattr(coral_dhw, "fetch_with_retry", get)
    return responses, calls
