"""Optional local preview backend using ReportLab charts and pdftoppm.

Import only from the explicit preview CLI. Normal bot/media modules do not
import ReportLab or require this renderer. No upload or publishing adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import subprocess

from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import (
    HEIGHT, WIDTH, TEMPLATE_VERSION, VARIABLE_LABELS, build_alt_text, chart_title, validate_graphic,
)

BACKGROUND = "#0A0A0A"
TEXT = "#F4F4F5"
MUTED = "#B5B5BD"
WARM = "#F87171"
GRID = "#35353B"
FONT_PATH = Path(__file__).with_name("fonts") / "DejaVuSansMono.ttf"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_preview(template, evidence, *, expected_evidence_sha256, output_dir, pdftoppm):
    evidence = validate_graphic(template, evidence, expected_evidence_sha256=expected_evidence_sha256)
    # Optional dependencies stay inside this local-only entry point.
    from reportlab import Version, rl_config
    from reportlab.graphics import renderPDF, renderSVG
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.graphics.widgets.markers import makeMarker
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    rl_config.invariant = True
    pdfmetrics.registerFont(TTFont("TheHeatMono", str(FONT_PATH)))
    rasterizer = Path(pdftoppm).resolve(strict=True)
    renderer = {"library": "ReportLab", "version": Version, "rasterizer_sha256": _digest(rasterizer),
                "implementation_sha256": _digest(Path(__file__)),
                "contract_sha256": _digest(Path(__file__).with_name("evidence_graphic.py")),
                "font_sha256": _digest(FONT_PATH), "width": WIDTH, "height": HEIGHT}
    identity = {"template": template, "template_version": TEMPLATE_VERSION,
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
    drawing = Drawing(WIDTH, HEIGHT)
    colors = {key: HexColor(value) for key, value in {"bg": BACKGROUND, "text": TEXT, "muted": MUTED, "warm": WARM, "grid": GRID}.items()}
    drawing.add(Rect(0, 0, WIDTH, HEIGHT, fillColor=colors["bg"], strokeColor=None))

    def text(x, y, value, size=24, color="text", anchor="start"):
        width = pdfmetrics.stringWidth(value, "TheHeatMono", size)
        if width > 1090 or (anchor == "start" and x + width > WIDTH - 30) or (anchor == "end" and x - width < 30):
            raise ValueError("Graphic label exceeds readable template bounds; revise label without clipping")
        drawing.add(String(x, y, value, fontName="TheHeatMono", fontSize=size, fillColor=colors[color], textAnchor=anchor))

    text(56, 622, "THEHEAT / DATA", 22, "muted")
    text(1144, 622, "SYNTHETIC · PRIVATE PREVIEW" if evidence["synthetic"] else "LOCAL REVIEW PREVIEW", 20, "warm", "end")
    text(56, 565, chart_title(template, evidence), 42)
    text(56, 520, evidence["location"], 27, "muted")
    as_of_label = datetime.fromisoformat(evidence["evidence_as_of"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    text(56, 484, "As of " + as_of_label, 20, "muted")

    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 110, 217, 1000, 250
    plot.strokeColor = None
    plot.xValueAxis.labels.fontName = plot.yValueAxis.labels.fontName = "TheHeatMono"
    plot.xValueAxis.labels.fontSize = plot.yValueAxis.labels.fontSize = 23
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
        plot.x, plot.width, plot.height = 378, 704, 205
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
            marker.size = 22
            marker.strokeColor = colors["warm"] if index else colors["text"]
            marker.fillColor = colors["bg"] if kind == "forecast" else marker.strokeColor
            marker.strokeWidth = 3
            plot.lines[index].symbol = marker
        text(56, 373, current["evidence_type"].capitalize(), 25)
        text(56, 337, f"{current['value']:g}{evidence['unit']}", 35, "warm")
        text(56, 270, prior["evidence_type"].capitalize() + " comparator", 22)
        text(56, 234, f"{prior['value']:g}{evidence['unit']}", 35)
        text(56, 203, prior["valid_time"][:10], 20, "muted")
        text(1082, 459, f"Difference {current['value'] - prior['value']:+g}{evidence['unit']}", 27, "warm", "end")
        text(56, 416, VARIABLE_LABELS[evidence["variable"]] + " / " + evidence["scope"], 20, "muted")
        text(1120, 170, evidence["unit"], 24, "muted", "end")
        source_products.append(prior["source"]["product"])
        valid_label = datetime.fromisoformat(current["valid_time"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        cutoff_label = datetime.fromisoformat(baseline["cutoff"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        subtitle = f"Valid {valid_label} / cutoff {cutoff_label}"
        text(56, 118, subtitle, 24)
        text(56, 84, baseline["scope"], 21, "muted")
    else:
        times = [datetime.fromisoformat(point["valid_time"].replace("Z", "+00:00")).astimezone(timezone.utc) for point in points]
        xs = [(value - times[0]).total_seconds() / 86400 for value in times]
        padding = (xs[-1] - xs[0]) * 0.04
        plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = xs[0] - padding, xs[-1] + padding
        daily = len({value.date() for value in times}) == len(times)
        same_day = len({value.date() for value in times}) == 1
        time_format = "%m-%d" if daily else ("%H:%M" if same_day else "%m-%d %H:%M")
        if not daily and len({value.strftime(time_format) for value in times}) != len(times):
            time_format += ":%S"
        labels = {x: value.strftime(time_format) for x, value in zip(xs, times)}
        for left, right in zip(xs, xs[1:]):
            gap = (right - left) / (plot.xValueAxis.valueMax - plot.xValueAxis.valueMin) * plot.width
            label_space = sum(pdfmetrics.stringWidth(labels[x], "TheHeatMono", 23) for x in (left, right)) / 2
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
            plot.lines[index].strokeWidth = 4
            plot.lines[index].strokeDashArray = [10, 7] if forecast else None
            if kind != "forecast-connector":
                marker = makeMarker("Diamond" if forecast else "FilledCircle")
                marker.size = 14
                marker.strokeColor = plot.lines[index].strokeColor
                marker.fillColor = colors["bg"] if forecast else colors["text"]
                marker.strokeWidth = 2.5
                plot.lines[index].symbol = marker
        text(60, 461, evidence["unit"], 23, "muted")
        legend = "   ".join(("◇ " if kind == "forecast" else "● ") + kind.capitalize() for kind, _ in series if kind != "forecast-connector")
        text(1095, 484, legend, 23, "muted", "end")
        text(56, 119, f"{times[0].strftime('%Y-%m-%d %H:%M')}–{times[-1].strftime('%Y-%m-%d %H:%M')} UTC", 23)
        text(56, 85, evidence["scope"], 21, "muted")
    drawing.add(plot)
    # Source labels are derived from evidence, not editable renderer copy.
    text(56, 47, "Source: " + " / ".join(dict.fromkeys(source_products)), 20, "muted")
    if evidence["synthetic"]:
        text(1144, 18, "Illustrative values only · not actual weather", 17, "warm", "end")
    else:
        text(1144, 18, f"Evidence {expected_evidence_sha256[:12]} · dated sample scope", 17, "muted", "end")
    (folder / "input.json").write_text(json.dumps({"template": template, "expected_evidence_sha256": expected_evidence_sha256, "evidence": evidence}, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    (folder / "alt.txt").write_text(build_alt_text(template, evidence) + "\n")
    renderPDF.drawToFile(drawing, str(folder / "preview.pdf"))
    svg = renderSVG.SVGCanvas((WIDTH, HEIGHT))
    style = svg.doc.createElement("style")
    style.setAttribute("type", "text/css")
    encoded_font = base64.b64encode(FONT_PATH.read_bytes()).decode("ascii")
    style.appendChild(svg.doc.createTextNode("@font-face{font-family:'TheHeatMono';src:url('data:font/ttf;base64," + encoded_font + "') format('truetype');font-weight:normal;font-style:normal;}"))
    svg.doc.documentElement.appendChild(style)
    for tag, value in (("title", chart_title(template, evidence)), ("desc", build_alt_text(template, evidence))):
        node = svg.doc.getElementsByTagName(tag)[0]
        node.replaceChild(svg.doc.createTextNode(value), node.firstChild)
    renderSVG.draw(drawing, svg, 0, 0)
    svg.save(str(folder / "preview.svg"))
    subprocess.run([str(rasterizer), "-r", "72", "-singlefile", "-png", str(folder / "preview.pdf"), str(folder / "preview")], check=True, capture_output=True, timeout=30)
    files = {name: _digest(folder / name) for name in ("input.json", "alt.txt", "preview.pdf", "preview.svg", "preview.png")}
    manifest = {"schema_version": 1, "cache_key": key, "binding": identity, "files": files,
                "synthetic": evidence["synthetic"], "alt_text": build_alt_text(template, evidence),
                "publication_approved": False, "scope": evidence["scope"]}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    for path in folder.iterdir():
        path.chmod(0o600)
    return manifest_path
