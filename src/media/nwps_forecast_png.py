"""Portable review image from the exact retained NWPS forecast specification."""

from datetime import datetime

from src.editorial.revisions import fingerprint
from src.media import gist_hazard_media as media
from src.media.evidence_graphic import HEIGHT, WIDTH, validate_graphic
from src.media.nwps_graphic_adapter import TEMPLATE, TEMPLATE_VERSION, nwps_alt_text

VERSION = "p31-nwps-png-1"
FORECAST = "#65d7f3"


def _render(evidence):
    canvas = media._Canvas("#111924")
    ink, muted, warm = media.INK, media.MUTED, media.WARM
    canvas.text((56, 112), "River-stage forecast", size=62, fill=ink)
    canvas.wrapped(56, 181, evidence["location"], size=46, fill=ink, lines=3, pitch=57)
    canvas.text((56, 369), "Issued " + evidence["issued_at"][:19].replace("T", " ") + " UTC", size=42, fill=muted)
    canvas.text((56, 425), "Checked " + evidence["evidence_as_of"][:19].replace("T", " ") + " UTC",
                size=42, fill=muted)
    canvas.text((56, 488), "Gauge stage (ft)", size=42, fill=muted)
    canvas.draw.line((839, 474, 915, 474), fill=FORECAST, width=6)
    canvas.text((1144, 488), "Forecast", size=42, fill=FORECAST, anchor="rs")

    left, right, top, bottom = 225, 1120, 543, 877
    points = evidence["points"]
    times = [datetime.fromisoformat(row["valid_time"]) for row in points]
    stages = [row["value"] for row in points]
    threshold = evidence["major_threshold_ft"]
    low, high = min(*stages, threshold), max(*stages, threshold)
    pad = max((high - low) / 8, 0.1)
    low, high = low - pad, high + pad

    def y_for(value):
        return round(bottom - (bottom - top) * (value - low) / (high - low))

    for tick in (low, (low + high) / 2, high):
        y = y_for(tick)
        canvas.draw.line((left, y, right, y), fill="#495566", width=2)
        canvas.text((left - 15, y + 12), f"{tick:.1f}", size=42, fill=muted, anchor="rs", maxwidth=150)
    y = y_for(threshold)
    for x in range(left, right, 24):
        canvas.draw.line((x, y, min(x + 15, right), y), fill=warm, width=4)

    span = times[-1] - times[0]
    line = [(round(left + (right - left) * (at - times[0]) / span), y_for(stage))
            for at, stage in zip(times, stages)]
    canvas.draw.line(line, fill=FORECAST, width=6)
    first = datetime.fromisoformat(evidence["first_major_at"])
    x, y = line[times.index(first)]
    canvas.draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=warm)
    canvas.text((56, 950), times[0].strftime("%m/%d %H:%M UTC"), size=42, fill=muted)
    canvas.text((1144, 950), times[-1].strftime("%m/%d %H:%M UTC"), size=42, fill=muted, anchor="rs")
    canvas.text((56, 1024), f"Major threshold: {threshold} ft", size=42, fill=warm)
    canvas.text((56, 1088), f"First supplied major point: {evidence['first_major_ft']} ft", size=42, fill=ink)
    canvas.text((56, 1152), first.strftime("%Y-%m-%d %H:%M:%S UTC"), size=42, fill=muted)
    canvas.text((56, 1224), f"NOAA / NWS · {evidence['gauge']} · {len(points)} points", size=42, fill=ink)
    canvas.text((56, 1290), "Saved forecast. Crossing time uncertain.", size=42, fill=muted)
    canvas.text((56, 1356), "Currentness requires a new source check.", size=42, fill=muted)
    return canvas.png()


def render_nwps_png(spec, source_context):
    """Bind image, description and labels to one requalified forecast capture."""
    evidence_sha = spec["expected_evidence_sha256"]
    evidence = validate_graphic(TEMPLATE, spec["evidence"], expected_evidence_sha256=evidence_sha)
    if evidence["synthetic"]:
        raise ValueError("The saved forecast preview requires a retained source packet")
    png = _render(evidence)
    alt = nwps_alt_text(evidence)
    binding = {
        "template": TEMPLATE, "template_version": TEMPLATE_VERSION, "renderer_version": VERSION,
        "source_evidence_sha256": evidence_sha, "source_context_sha256": fingerprint(source_context),
        "png_sha256": media._digest(png), "alt_sha256": media._digest(alt.encode("utf-8")),
        "renderer_sha256": media._digest(media._resource("src/media/nwps_forecast_png.py")),
        "canvas_sha256": media._digest(media._resource("src/media/gist_hazard_media.py")),
        "codec_sha256": media._digest(media._resource("src/media/canonical_png.py")),
        "font_sha256": media._digest(media._resource(media.FONT)),
    }
    return {"binding": binding, "cache_key": fingerprint(binding), "png": png,
            "alt_text": alt, "scope": evidence["scope"], "title": "River-stage forecast",
            "width": WIDTH, "height": HEIGHT}
