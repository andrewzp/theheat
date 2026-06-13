"""Hot 10 leaderboard PNG card renderer."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
HEIGHT = 675
BACKGROUND = (10, 10, 10)
TEXT = (244, 244, 245)
MUTED = (161, 161, 170)
WARM = (248, 113, 113)
COOL = (96, 165, 250)

_FONT_PATH = Path(__file__).with_name("fonts") / "DejaVuSansMono.ttf"
_DEG_C = "\N{DEGREE SIGN}C"


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_PATH), size=size)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalise_rows(cities: list[dict]) -> list[dict[str, Any]]:
    rows = []
    for idx, raw in enumerate(cities[:10], start=1):
        city = str(raw.get("city") or "").strip() or "Unknown"
        country = str(raw.get("country") or "").strip()
        rows.append({
            "rank": _int(raw.get("rank"), idx) or idx,
            "city": city,
            "country": country,
            "anomaly_c": _float(raw.get("anomaly_c")),
            "temp_high_c": _float(raw.get("temp_high_c")),
        })
    return rows


def _format_anomaly(value: float) -> str:
    return f"{value:+.1f} {_DEG_C}"


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    trimmed = text
    while trimmed and draw.textlength(trimmed + suffix, font=font) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed.rstrip() + suffix) if trimmed else suffix


def render_hot10_card(cities: list[dict]) -> bytes:
    """Render a deterministic 1200x675 PNG card for Hot 10 rows."""
    rows = _normalise_rows(cities)
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    rank_font = _font(28)
    label_font = _font(28)
    value_font = _font(28)

    max_abs = max((abs(row["anomaly_c"]) for row in rows), default=1.0) or 1.0
    row_step = 61
    row_top = 35
    rank_x = 44
    label_x = 110
    bar_x = 560
    bar_max = 360
    value_x = 970
    bar_h = 18

    for idx, row in enumerate(rows):
        y = row_top + idx * row_step
        anomaly = row["anomaly_c"]
        color = WARM if anomaly >= 0 else COOL
        bar_w = int(bar_max * (abs(anomaly) / max_abs))
        if anomaly != 0:
            bar_w = max(8, bar_w)

        country = f", {row['country']}" if row["country"] else ""
        label = _fit_text(draw, f"{row['city']}{country}", label_font, 410)
        draw.text((rank_x, y), f"{row['rank']:>2}", fill=MUTED, font=rank_font)
        draw.text((label_x, y), label, fill=TEXT, font=label_font)
        draw.text((value_x, y), _format_anomaly(anomaly), fill=TEXT, font=value_font)

        bar_y = y + 34
        draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=color)

    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def build_hot10_alt_text(cities: list[dict]) -> str:
    """Build X alt text for the Hot 10 card, capped at 420 characters."""
    rows = _normalise_rows(cities)
    if not rows:
        return "Hot 10 temperature anomaly ranking unavailable."

    leader = rows[0]
    compact = "; ".join(
        f"{row['rank']}. {row['city']} {_format_anomaly(row['anomaly_c'])}"
        for row in rows[:5]
    )
    more = max(0, len(rows) - 5)
    suffix = f"; and {more} more" if more else ""
    text = (
        f"{leader['city']} leads at {_format_anomaly(leader['anomaly_c'])}. "
        f"Top 10 cities by temperature anomaly: {compact}{suffix}"
    )
    if len(text) <= 420:
        return text
    return text[:417].rstrip() + "..."
