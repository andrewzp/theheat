"""Tests for Hot 10 media card rendering."""

from __future__ import annotations

from io import BytesIO


def _sample_rows() -> list[dict]:
    cities = [
        ("Phoenix", "US", 8.1, 44.2),
        ("Delhi", "IN", 7.4, 42.8),
        ("Cairo", "EG", 6.8, 39.5),
        ("Athens", "GR", 5.9, 36.0),
        ("Seville", "ES", 4.7, 38.1),
        ("Lima", "PE", -4.1, 17.0),
        ("Tokyo", "JP", 3.2, 31.4),
        ("Perth", "AU", 2.7, 28.9),
        ("Nairobi", "KE", -2.4, 21.8),
        ("Toronto", "CA", 1.9, 25.5),
    ]
    return [
        {
            "rank": idx,
            "city": city,
            "country": country,
            "anomaly_c": anomaly,
            "temp_high_c": temp_high,
        }
        for idx, (city, country, anomaly, temp_high) in enumerate(cities, start=1)
    ]


def test_card_renders_10_rows_deterministic():
    from PIL import Image

    from src.media.hot10_card import render_hot10_card

    rows = _sample_rows()
    first = render_hot10_card(rows)
    second = render_hot10_card(rows)

    assert first == second
    assert first.startswith(b"\x89PNG\r\n\x1a\n")

    image = Image.open(BytesIO(first))
    assert image.format == "PNG"
    assert image.size == (1200, 675)
    assert image.getpixel((8, 8))[:3] == (10, 10, 10)

    warm = (248, 113, 113)
    cool = (96, 165, 250)
    colored_ys = sorted({
        y
        for y in range(image.height)
        for x in range(image.width)
        if image.getpixel((x, y))[:3] in {warm, cool}
    })

    clusters = []
    for y in colored_ys:
        if not clusters or y > clusters[-1][-1] + 1:
            clusters.append([y])
        else:
            clusters[-1].append(y)

    assert len(clusters) == 10
    assert any(
        image.getpixel((x, y))[:3] == warm
        for y in range(image.height)
        for x in range(image.width)
    )
    assert any(
        image.getpixel((x, y))[:3] == cool
        for y in range(image.height)
        for x in range(image.width)
    )


def test_alt_text_under_420_and_names_leader():
    from src.media.hot10_card import build_hot10_alt_text

    alt = build_hot10_alt_text(_sample_rows())

    assert len(alt) <= 420
    assert "Phoenix" in alt
    assert "+8.1" in alt
    assert "Top 10 cities by temperature anomaly: " in alt
    assert "and 5 more" in alt
