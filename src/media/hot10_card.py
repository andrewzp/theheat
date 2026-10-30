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


# ---------------------------------------------------------------- qualified bulletin (D1)

BULLETIN_TEXT_WIDTH = 1112
MAX_BULLETIN_ALT = 1000  # The existing house delivery bound, Unicode scalars and UTF-8 bytes.
LEGEND = ("above its normal", "below its normal")


class BulletinWithheld(ValueError):
    """A refused image; the text draft stays usable and unchanged."""


def _bulletin(bundle: dict) -> dict:
    from src.editorial.hot10_contract import validate_bundle

    failures = validate_bundle(bundle)
    if failures:
        raise BulletinWithheld("Hot 10 image withheld: retained bulletin fails its contract (" + failures[0] + ")")
    return bundle["raw_signal_dump"]


def _signed(value: float) -> str:
    return f"{value:+.1f}".replace("-", "\N{MINUS SIGN}") + " " + _DEG_C


def render_hot10_bulletin(bundle: dict) -> bytes:
    """A 1200x675 colour card from the exact retained qualified rows; refuses rather than truncating.

    Bars are departures from each city's own point monthly normal on one common
    scale including zero; warm means above normal and cool below, and every
    meaning is also written as text (legend, values, scope), never colour alone.
    """
    raw = _bulletin(bundle)
    rows, universe = raw["cities"], raw["universe"]
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    small, body, strong = _font(20), _font(24), _font(26)

    def text(xy, value, font, fill, *, max_width=BULLETIN_TEXT_WIDTH):
        if draw.textlength(value, font=font) > max_width:
            raise BulletinWithheld("Hot 10 image withheld: label exceeds readable width")
        draw.text(xy, value, font=font, fill=fill)

    days = " / ".join(universe["local_days"])
    text((44, 22), "HOT 10 \N{MIDDLE DOT} FORECAST DAILY HIGH VS NORMAL", strong, TEXT)
    text((44, 58), f"{days} local \N{MIDDLE DOT} {universe['qualified_cities']} of {universe['sampled_cities']} "
                   "sampled cities qualified", small, MUTED)
    scale = max(abs(row["anomaly_c"]) for row in rows) or 1.0
    top, step, bar_x, bar_max = 96, 46, 640, 300
    for index, row in enumerate(rows):
        y = top + index * step
        warm = row["anomaly_c"] >= 0
        width = max(6, int(bar_max * abs(row["anomaly_c"]) / scale)) if row["anomaly_c"] else 0
        text((44, y), f"{row['rank']:>2}", body, MUTED, max_width=40)
        text((92, y), f"{row['city']}, {row['country']}", body, TEXT, max_width=530)
        draw.rectangle((bar_x, y + 6, bar_x + width, y + 26), fill=WARM if warm else COOL)
        text((bar_x + bar_max + 16, y), _signed(row["anomaly_c"]), body, TEXT, max_width=150)
        text((92, y + 26), f"forecast {row['temp_high_c']:.1f} vs normal {row['normal_high_c']:.1f} {_DEG_C}",
             _font(16), MUTED, max_width=530)
    legend_y = top + len(rows) * step + 4
    for offset, (label, colour) in enumerate(zip(LEGEND, (WARM, COOL), strict=True)):
        x = 44 + offset * 300
        draw.rectangle((x, legend_y + 4, x + 24, legend_y + 22), fill=colour)
        text((x + 34, legend_y), label, small, TEXT, max_width=250)
    text((644, legend_y), f"bar = departure, common {_DEG_C} scale", small, MUTED, max_width=520)
    text((44, legend_y + 30), "Source: Open-Meteo forecast daily high \N{MIDDLE DOT} Meteostat point monthly normal",
         _font(17), MUTED)
    text((44, legend_y + 54), "Sampled cities only; not observations, records or the world's hottest places",
         _font(17), MUTED)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def hot10_bulletin_alt_text(bundle: dict) -> str:
    """Complete description of every ranked row and the scope; refuses rather than truncating."""
    raw = _bulletin(bundle)
    universe = raw["universe"]
    rows = "; ".join(
        f"{row['rank']}. {row['city']}, {row['country']} {row['anomaly_c']:+.1f} "
        f"({row['temp_high_c']:.1f} vs {row['normal_high_c']:.1f})"
        for row in raw["cities"])
    value = (f"Hot 10 forecast daily highs ranked by departure from each city's point monthly normal, among "
             f"{universe['qualified_cities']} qualified of {universe['sampled_cities']} sampled cities; local days "
             f"{', '.join(universe['local_days'])}; all values in {_DEG_C} as departure (forecast vs normal): {rows}. "
             "Warm bars are above normal, cool bars below, on one common scale. Open-Meteo forecast and "
             "Meteostat normals; not observations, records or the world's hottest places.")
    if len(value) > MAX_BULLETIN_ALT or len(value.encode("utf-8")) > MAX_BULLETIN_ALT:
        raise BulletinWithheld("Hot 10 image withheld: complete description exceeds the delivery bound")
    return value
