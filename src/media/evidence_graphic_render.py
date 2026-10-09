"""Optional evidence graphics, shared by in-memory SVG and local PDF/PNG previews.

ReportLab is imported only after validation in an explicit render entry point.
Normal bot/media modules do not require it. No upload or publishing adapter.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import base64
import hashlib
import json
from importlib.resources import files
from io import BytesIO, StringIO
from threading import RLock
from pathlib import Path
import subprocess

from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import (
    HEIGHT, WIDTH, template_version, adapter_filename, VARIABLE_LABELS, build_alt_text, chart_title, date_only,
    point_label, validate_graphic,
)

BACKGROUND = "#0A0A0A"
TEXT = "#F4F4F5"
MUTED = "#B5B5BD"
WARM = "#F87171"
GRID = "#35353B"
FONT_RESOURCE = "fonts/DejaVuSansMono.ttf"
MAX_SVG_BYTES = 1_000_000
_RENDER_LOCK = RLock()


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_preview(template, evidence, *, expected_evidence_sha256, output_dir, pdftoppm):
    """Retain the existing immutable five-asset local package."""
    with _RENDER_LOCK:
        return _render_preview(template, evidence, expected_evidence_sha256=expected_evidence_sha256,
                               output_dir=output_dir, pdftoppm=pdftoppm)


def _resource(name):
    return files("src.media").joinpath(name).read_bytes()


def _resource_digest(name):
    return hashlib.sha256(_resource(name)).hexdigest()


def _renderer_identity(template, evidence):
    from reportlab import Version

    renderer = {"library": "ReportLab", "version": Version,
                "implementation_sha256": _resource_digest("evidence_graphic_render.py"),
                "contract_sha256": _resource_digest("evidence_graphic.py"),
                "font_sha256": _resource_digest(FONT_RESOURCE), "width": WIDTH, "height": HEIGHT}
    if "input_binding" in evidence:
        renderer["adapter_sha256"] = _resource_digest(adapter_filename(template))
    return renderer


def render_svg(template, evidence, *, expected_evidence_sha256):
    """Return validated private preview bytes without files, PDF, network or approval.

    The caller owns access control and exact saved-draft selection. This rendering
    identity alone does not establish source authenticity or text/graphic agreement.
    """
    evidence = validate_graphic(template, evidence, expected_evidence_sha256=expected_evidence_sha256)
    with _RENDER_LOCK:
        renderer = {**_renderer_identity(template, evidence), "format": "svg", "schema_version": 1}
        binding = {"template": template, "template_version": template_version(template),
                   "source_evidence_sha256": expected_evidence_sha256, "renderer": renderer}
        svg = _svg_bytes(_drawing(template, evidence), template, evidence)
    return {"schema_version": 1, "cache_key": fingerprint(binding), "binding": binding,
            "svg": svg, "svg_sha256": hashlib.sha256(svg).hexdigest(),
            "title": chart_title(template, evidence), "alt_text": build_alt_text(template, evidence),
            "width": WIDTH, "height": HEIGHT, "synthetic": evidence["synthetic"],
            "scope": evidence["scope"], "publication_approved": False}


def _render_preview(template, evidence, *, expected_evidence_sha256, output_dir, pdftoppm):
    evidence = validate_graphic(template, evidence, expected_evidence_sha256=expected_evidence_sha256)
    from reportlab.graphics import renderPDF

    rasterizer = Path(pdftoppm).resolve(strict=True)
    renderer = {**_renderer_identity(template, evidence), "rasterizer_sha256": _digest(rasterizer)}
    identity = {"template": template, "template_version": template_version(template),
                "source_evidence_sha256": expected_evidence_sha256, "renderer": renderer}
    key = fingerprint(identity)
    folder = Path(output_dir).resolve() / key
    manifest_path = folder / "manifest.json"
    if folder.exists():
        if folder.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("Incomplete/unsafe cached preview; never overwrite it silently")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("binding") != identity:
            raise ValueError("Cached media binding mismatch")
        expected_metadata = {"schema_version": 1, "cache_key": key, "synthetic": evidence["synthetic"],
                             "alt_text": build_alt_text(template, evidence), "publication_approved": False,
                             "scope": evidence["scope"]}
        if any(manifest.get(name) != value for name, value in expected_metadata.items()):
            raise ValueError("Cached preview metadata changed")
        if set(manifest.get("files", {})) != {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}:
            raise ValueError("Cached preview asset set incomplete")
        expected_input = {"template": template, "expected_evidence_sha256": expected_evidence_sha256, "evidence": evidence}
        if json.loads((folder / "input.json").read_text()) != expected_input:
            raise ValueError("Cached input differs from bound evidence")
        for name, digest in manifest["files"].items():
            if name not in {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}:
                raise ValueError("Unknown cached asset")
            path = folder / name
            if path.is_symlink() or _digest(path) != digest:
                raise ValueError("Cached preview content changed")
        return manifest_path
    folder.mkdir(parents=True, mode=0o700)
    folder.chmod(0o700)
    drawing = _drawing(template, evidence)
    (folder / "input.json").write_text(json.dumps({"template": template, "expected_evidence_sha256": expected_evidence_sha256, "evidence": evidence}, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    (folder / "alt.txt").write_text(build_alt_text(template, evidence) + "\n")
    renderPDF.drawToFile(drawing, str(folder / "preview.pdf"))
    (folder / "preview.svg").write_bytes(_svg_bytes(drawing, template, evidence, legacy_doctype=True))
    subprocess.run([str(rasterizer), "-r", "72", "-singlefile", "-png", str(folder / "preview.pdf"), str(folder / "preview")], check=True, capture_output=True, timeout=30)
    files = {name: _digest(folder / name) for name in ("input.json", "alt.txt", "preview.pdf", "preview.svg", "preview.png")}
    manifest = {"schema_version": 1, "cache_key": key, "binding": identity, "files": files,
                "synthetic": evidence["synthetic"], "alt_text": build_alt_text(template, evidence),
                "publication_approved": False, "scope": evidence["scope"]}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    for path in folder.iterdir():
        path.chmod(0o600)
    return manifest_path


class _BoundedSvg(StringIO):
    """Refuse oversized serialized UTF-8 output before returning any bytes."""
    def __init__(self):
        super().__init__()
        self.byte_count = 0

    def write(self, value):
        self.byte_count += len(value.encode("utf-8"))
        if self.byte_count > MAX_SVG_BYTES:
            raise ValueError("Graphic exceeds SVG byte limit")
        return super().write(value)


def _svg_bytes(drawing, template, evidence, *, legacy_doctype=False):
    from reportlab.graphics import renderSVG

    svg = renderSVG.SVGCanvas((WIDTH, HEIGHT))
    # Browser previews must not reference ReportLab's external SVG 1.0 DTD.
    # Preserve the existing local-package bytes and their immutable history.
    if not legacy_doctype and svg.doc.doctype is not None:
        svg.doc.removeChild(svg.doc.doctype)
    style = svg.doc.createElement("style")
    style.setAttribute("type", "text/css")
    encoded_font = base64.b64encode(_resource(FONT_RESOURCE)).decode("ascii")
    style.appendChild(svg.doc.createTextNode("@font-face{font-family:'TheHeatMono';src:url('data:font/ttf;base64," + encoded_font + "') format('truetype');font-weight:normal;font-style:normal;}"))
    svg.doc.documentElement.appendChild(style)
    for tag, value in (("title", chart_title(template, evidence)), ("desc", build_alt_text(template, evidence))):
        node = svg.doc.getElementsByTagName(tag)[0]
        node.replaceChild(svg.doc.createTextNode(value), node.firstChild)
    renderSVG.draw(drawing, svg, 0, 0)
    output = _BoundedSvg()
    svg.save(output)
    return output.getvalue().encode("utf-8")


def _drawing(template, evidence):
    from reportlab import rl_config
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.graphics.widgets.markers import makeMarker
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    rl_config.invariant = True
    pdfmetrics.registerFont(TTFont("TheHeatMono", BytesIO(_resource(FONT_RESOURCE))))
    drawing = Drawing(WIDTH, HEIGHT)
    colors = {key: HexColor(value) for key, value in {"bg": BACKGROUND, "text": TEXT, "muted": MUTED, "warm": WARM, "grid": GRID}.items()}
    drawing.add(Rect(0, 0, WIDTH, HEIGHT, fillColor=colors["bg"], strokeColor=None))

    def text(x, y, value, size=40, color="text", anchor="start"):
        width = pdfmetrics.stringWidth(value, "TheHeatMono", size)
        if (size < 40 or width > 1088 or y < 38 or y + size > HEIGHT - 20
                or (anchor == "start" and x + width > WIDTH - 40)
                or (anchor == "end" and x - width < 40)):
            raise ValueError("Graphic label exceeds readable template bounds; revise label without clipping")
        drawing.add(String(x, y, value, fontName="TheHeatMono", fontSize=size, fillColor=colors[color], textAnchor=anchor))

    def block(y, value, *, size=40, color="muted", bottom=40):
        # Wrap at actual font widths; dates/words are never truncated or shrunk.
        line = ""
        for word in value.split():
            candidate = (line + " " + word).strip()
            if pdfmetrics.stringWidth(candidate, "TheHeatMono", size) > 1088:
                if not line:
                    raise ValueError("Graphic word exceeds readable width")
                if y < bottom:
                    raise ValueError("Graphic qualifications exceed readable template capacity")
                text(56, y, line, size, color)
                y -= size + 12
                line = word
            else:
                line = candidate
        if line:
            if y < bottom:
                raise ValueError("Graphic qualifications exceed readable template capacity")
            text(56, y, line, size, color)
            y -= size + 12
        return y

    text(56, 1418, "THEHEAT", 48)
    text(1144, 1418, "SYNTHETIC DATA" if evidence["synthetic"] else "REVIEW PREVIEW", 40, "warm", "end")
    if template == "modis_thermal_detections":
        from src.media.fire_graphic_adapter import coordinate_label, frp_axis, frp_label
        from reportlab.graphics.shapes import Line
        text(56, 1320, chart_title(template, evidence), 62)
        text(56, 1245, f"NASA FIRMS · {evidence['satellite']} / MODIS", 40, "muted")
        text(56, 1185, evidence["acquired_at"][:16].replace("T", " ") + " UTC (minute)", 40, "muted")
        text(56, 1125, "Pixel FRP · MW (rounded to 1 decimal)", 40, "muted")
        top = frp_axis([point["frp_source"] for point in evidence["points"]])
        for index, point in enumerate(evidence["points"]):
            y = 1045 - index * 125
            place = point["label"] + " · " + coordinate_label(point)
            value = frp_label(point["frp_source"])
            if sum(pdfmetrics.stringWidth(label, "TheHeatMono", 40) for label in (place, value)) > 1060:
                raise ValueError("MODIS point labels exceed readable row width")
            text(56, y, place, 40)
            text(1144, y, value, 40, "text", "end")
            drawing.add(Line(56, y - 58, 1144, y - 58, strokeColor=colors["grid"], strokeWidth=2))
            drawing.add(Rect(56, y - 58, point["frp_source"] / top * 1088, 36,
                             fillColor=colors["text"], strokeColor=None))
        for fraction, anchor in ((0, "start"), (0.5, "middle"), (1, "end")):
            x = 56 + fraction * 1088
            text(x, 535, f"{top * fraction:g}", 40, "muted", anchor)
        y = 450
        for note in [
            "Pixel centers; coordinates rounded to 4 decimals.",
            "Not fire perimeters or separate-fire counts.",
            "UTC minute does not establish simultaneity.",
            "FRP is radiative power, not temperature.",
            "Not burned area or total physical-fire intensity.",
            *(["Illustrative values; not actual weather."] if evidence["synthetic"] else []),
        ]:
            y = block(y, note)
    elif template == "pm25_forecast_day":
        from src.media.air_quality_graphic_adapter import concentration, forecast_axis
        from reportlab.graphics.shapes import Circle, Line
        text(56, 1320, chart_title(template, evidence), 62)
        block(1240, evidence["location"], size=48, color="text", bottom=1150)
        text(56, 1080, "Local day " + evidence["valid_date"], 40, "muted")
        text(56, 1025, evidence["timezone"], 40, "muted")
        text(56, 965, "PM2.5 · μg/m³", 40, "muted")
        top, ticks = forecast_axis(evidence["values"])
        plot_left, bottom, width, height = 180, 630, 920, 270
        for tick in ticks:
            y = bottom + tick / top * height
            drawing.add(Line(plot_left, y, plot_left + width, y, strokeColor=colors["grid"], strokeWidth=2))
            text(plot_left - 20, y - 12, f"{tick:g}", 40, "muted", "end")
        for hour in (0, 6, 12, 18, 23):
            x = plot_left + hour / 23 * width
            drawing.add(Line(x, bottom - 8, x, bottom, strokeColor=colors["muted"], strokeWidth=2))
            text(x, bottom - 62, f"{hour:02d}", 40, "muted", "middle")
        points = [(plot_left + hour / 23 * width, bottom + value / top * height)
                  for hour, value in enumerate(evidence["values"])]
        for first, second in zip(points, points[1:]):
            drawing.add(Line(*first, *second, strokeColor=colors["text"], strokeWidth=4))
        for x, y in points:
            drawing.add(Circle(x, y, 5, fillColor=colors["text"], strokeColor=None))
        text(1100, 507, "Local hour", 40, "muted", "end")
        text(56, 507, "Mean of 24 samples", 40, "muted")
        text(56, 405, concentration(evidence["sample_mean"]) + " μg/m³", 96)
        lat, lon = evidence["grid_location"]
        notes = [f"Grid: {abs(lat):.4f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}",
                 "Model forecast; 24 hourly samples.", "Not station measurements.",
                 "Source: CAMS via Open-Meteo"]
        if evidence["synthetic"]:
            notes.append("Illustrative values; not actual weather.")
        y = 315
        for note in notes:
            y = block(y, note)
    elif template == "crw_regional_anomaly":
        from src.media.crw_graphic_adapter import anomaly_axis_limit, signed_anomaly
        from reportlab.graphics.shapes import Line
        text(56, 1320, chart_title(template, evidence), 62)
        block(1240, evidence["location"], size=48, color="text", bottom=1150)
        text(56, 1090, "Product date " + evidence["valid_date"], 40, "muted")
        text(56, 935, signed_anomaly(evidence["value"]) + "°C", 124, "warm")
        limit = anomaly_axis_limit(evidence["value"])
        center, half, axis_y = WIDTH / 2, 470, 795
        endpoint = center + evidence["value"] / limit * half
        drawing.add(Rect(min(center, endpoint), axis_y + 15, abs(endpoint - center), 50,
                         fillColor=colors["warm"], strokeColor=None))
        drawing.add(Line(center - half, axis_y, center + half, axis_y, strokeColor=colors["muted"], strokeWidth=2))
        for x in (center - half, center, center + half):
            drawing.add(Line(x, axis_y - 8, x, axis_y + 70, strokeColor=colors["muted"], strokeWidth=2))
        text(center - half, axis_y - 65, f"−{limit}°C", 40, "muted")
        text(center, axis_y - 65, "0", 40, "muted", "middle")
        text(center + half, axis_y - 65, f"+{limit}°C", 40, "muted", "end")
        notes = ["Relative to CRW daily climatology",
                 "Reference: 1985–1990 + 1993",
                 f"{evidence['valid_cells']} valid / {evidence['total_cells']} sampled cells",
                 "Latitude-weighted satellite analysis; 1° sample spacing, not a full-grid regional average.",
                 "Source: NOAA Coral Reef Watch v3.1"]
        if evidence["synthetic"]:
            notes.append("Illustrative values; not actual weather.")
        bottom = 635
        for note in notes:
            bottom = block(bottom, note)
    else:
        text(56, 1312, chart_title(template, evidence), 48 if template == "temperature_trajectory" else 62)
        location_bottom = block(1245, evidence["location"], color="text", bottom=1190)
        as_of_label = datetime.fromisoformat(evidence["evidence_as_of"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        text(56, location_bottom - 12, "As of " + as_of_label, 40, "muted")
        if template == "temperature_comparator":
            text(56, location_bottom - 76, VARIABLE_LABELS[evidence["variable"]], 40, "muted")

        plot = LinePlot()
        plot.x, plot.y, plot.width, plot.height = 135, 755, 940, 280
        plot.strokeColor = None
        plot.xValueAxis.labels.fontName = plot.yValueAxis.labels.fontName = "TheHeatMono"
        plot.xValueAxis.labels.fontSize = plot.yValueAxis.labels.fontSize = 40
        plot.xValueAxis.labels.fillColor = plot.yValueAxis.labels.fillColor = colors["muted"]
        plot.xValueAxis.strokeColor = plot.yValueAxis.strokeColor = colors["grid"]
        plot.xValueAxis.tickDown = 8
        plot.yValueAxis.visibleGrid = True
        plot.yValueAxis.gridStrokeColor = colors["grid"]
        plot.yValueAxis.gridStrokeWidth = 1
        plot.yValueAxis.labels.dx = -16
        points = evidence["points"]
        source_products = []
        for point in points:
            if point["source"]["product"] not in source_products:
                source_products.append(point["source"]["product"])

        if template == "temperature_comparator":
            baseline, current = evidence["baseline"], points[0]
            prior = baseline["point"]
            plot.x, plot.width, plot.height = 555, 515, 250
            plot.yValueAxis.visible = False
            plot.yValueAxis.visibleGrid = False
            plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = -0.5, 1.5
            low, high = sorted((prior["value"], current["value"]))
            padding = max(1.5, (high - low) * 0.75)
            plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = low - padding, high + padding
            plot.xValueAxis.labelTextFormat = lambda value: f"{value:g}"
            plot.xValueAxis.maximumTicks = 5
            plot.data = [[(prior["value"], 0)], [(current["value"], 1)]]
            plot.joinedLines = False
            for index, kind in enumerate((prior["evidence_type"], current["evidence_type"])):
                marker = makeMarker("Diamond" if kind == "forecast" else "FilledCircle")
                marker.size = 30
                marker.strokeColor = colors["warm"] if index else colors["text"]
                marker.fillColor = colors["bg"] if kind == "forecast" else marker.strokeColor
                marker.strokeWidth = 3
                plot.lines[index].symbol = marker
            text(56, 951, current["evidence_type"].capitalize(), 40)
            text(56, 878, f"{current['value']:g}{evidence['unit']}", 62, "warm")
            text(56, 792, "Comparator", 40)
            text(56, 725, f"{prior['value']:g}{evidence['unit']}", 62)
            text(1144, 1015, f"Difference {current['value'] - prior['value']:+g}{evidence['unit']}", 40, "warm", "end")
            text(1144, 687, evidence["unit"], 40, "muted", "end")
            source_products.append(prior["source"]["product"])
            notes = ["Current: " + point_label(current, evidence),
                     "Observed comparator: " + point_label(prior, evidence),
                     "Archive: " + baseline["start"] + " to " + baseline["cutoff"],
                     baseline["scope"], evidence["scope"]]
        else:
            times = ([date.fromisoformat(point["valid_date"]) for point in points] if date_only(evidence) else
                     [datetime.fromisoformat(point["valid_time"].replace("Z", "+00:00")).astimezone(timezone.utc) for point in points])
            xs = [(value - times[0]).total_seconds() / 86400 for value in times]
            padding = (xs[-1] - xs[0]) * 0.04
            plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = xs[0] - padding, xs[-1] + padding
            days = [value.date() if isinstance(value, datetime) else value for value in times]
            daily = len(set(days)) == len(times)
            same_day = len(set(days)) == 1
            time_format = "%m-%d" if daily else ("%H:%M" if same_day else "%m-%d %H:%M")
            if not daily and len({value.strftime(time_format) for value in times}) != len(times):
                time_format += ":%S"
            labels = {x: value.strftime(time_format) for x, value in zip(xs, times)}
            for left, right in zip(xs, xs[1:]):
                gap = (right - left) / (plot.xValueAxis.valueMax - plot.xValueAxis.valueMin) * plot.width
                label_space = sum(pdfmetrics.stringWidth(labels[x], "TheHeatMono", 40) for x in (left, right)) / 2
                if gap < label_space + 12:
                    raise ValueError("Trajectory time labels would overlap; use fewer reviewed points")
            plot.xValueAxis.valueSteps = xs
            plot.xValueAxis.labelTextFormat = lambda value: labels.get(value, "")
            values = [point["value"] for point in points]
            plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = min(values) - 2, max(values) + 2
            plot.yValueAxis.maximumTicks = 5
            plot.yValueAxis.labelTextFormat = lambda value: f"{value:g}"
            series = []
            for kind in dict.fromkeys(point["evidence_type"] for point in points):
                series.append((kind, [(x, point["value"]) for x, point in zip(xs, points) if point["evidence_type"] == kind]))
            if len(series) == 2:
                series.append(("forecast-connector", [series[0][1][-1], series[1][1][0]]))
            plot.data = [rows for _, rows in series]
            plot.joinedLines = True
            for index, (kind, _) in enumerate(series):
                forecast = kind.startswith("forecast")
                plot.lines[index].strokeColor = colors["warm"] if forecast else colors["text"]
                plot.lines[index].strokeWidth = 5
                plot.lines[index].strokeDashArray = [10, 7] if forecast else None
                if kind != "forecast-connector":
                    marker = makeMarker("Diamond" if forecast else "FilledCircle")
                    marker.size = 24
                    marker.strokeColor = plot.lines[index].strokeColor
                    marker.fillColor = colors["bg"] if forecast else colors["text"]
                    marker.strokeWidth = 2.5
                    plot.lines[index].symbol = marker
            text(60, 1060, evidence["unit"], 40, "muted")
            legend = "   ".join(("◇ " if kind == "forecast" else "● ") + kind.capitalize() for kind, _ in series if kind != "forecast-connector")
            text(1144, 1070, legend, 40, "muted", "end")
            notes = [evidence["scope"],
                     "From " + point_label(points[0], evidence),
                     "Through " + point_label(points[-1], evidence)]
        drawing.add(plot)
        notes.append("Source: " + " / ".join(dict.fromkeys(source_products)))
        if date_only(evidence):
            notes.append("Dates are source-calendar labels; reporting interval and timezone unknown.")
        if template == "temperature_comparator" and "no official record" not in evidence["baseline"]["scope"].lower():
            notes.append("Dated sample comparison; no official record.")
        if evidence["synthetic"]:
            notes.append("Illustrative values; not actual weather.")
        bottom = 610
        for note in notes:
            bottom = block(bottom, note)
    return drawing
