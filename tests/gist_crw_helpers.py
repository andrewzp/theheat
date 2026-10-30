"""Invented, source-shaped CRW inputs with varied cells and exclusions (never real weather)."""
import math

from src.data import crw_contract as source
from src.data.ocean_sst_anomaly import REGION_REGISTRY, RegionalSSTAnomalyEvent, _build_url, _detect_tier
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.two_bot.intern.marine import build_regional_sst_anomaly_bundle
from tests.crw_fixtures import DAY, RETRIEVED, csv_body, metadata_body, metadata_receipt


def varied_inputs(slug="caribbean", *, base=3.2, spread=1.6, hole_every=7, day=DAY, retrieved=RETRIEVED):
    """A smooth invented warm gradient with every ``hole_every``-th cell excluded (NaN)."""
    region = next(r for r in REGION_REGISTRY if r.slug == slug)
    selected = {}
    for index, lat in enumerate(range(int(region.lat_n), int(region.lat_s) - 1, -1)):
        for jndex, lon in enumerate(range(int(region.lon_w), int(region.lon_e) + 1)):
            if hole_every and (index * 31 + jndex) % hole_every == 0:
                continue
            wave = math.sin(jndex / 3.0) * 0.4
            selected[(float(lat), float(lon))] = round(base + spread * (jndex / max(1, region.lon_e - region.lon_w) - 0.5) + wave, 2)
    raw = csv_body(region, day=day, selected=selected)
    sample = source.decode_csv(raw.decode(), region)
    weights = [math.cos(math.radians(lat)) for lat, _ in sample.cells]
    mean = math.fsum(v * w for (_, v), w in zip(sample.cells, weights)) / math.fsum(weights)
    tier = _detect_tier(mean)
    assert tier and tier >= 1, "invented gradient must form a warm-anomaly event"
    provenance = source.provenance(body=raw, url=_build_url(region), retrieved_at=retrieved,
                                   timestamp=f"{day}T12:00:00Z", region=region, mean=round(mean, 2),
                                   valid_cells=len(sample.cells), total_cells=sample.total_cells,
                                   sampled_bounds=sample.sampled_bounds, leg="coastwatch_erddap",
                                   metadata=metadata_receipt())
    bundle = build_regional_sst_anomaly_bundle(RegionalSSTAnomalyEvent(
        region.slug, region.display_name, day, round(mean, 2), tier, len(sample.cells),
        f"sst_anom_{region.slug}_tier{tier}_{day}", provenance=provenance))
    packet = {"schema_version": 1, "csv_utf8": raw.decode(), "metadata_utf8": metadata_body().decode(),
              "csv_retrieved_at": retrieved, "metadata_retrieved_at": retrieved}
    return story_bundle_snapshot(bundle), packet


CLOCK = "2026-06-16T13:00:00Z"


def collected_inputs(slug="caribbean"):
    """varied_inputs whose event carries the collector's exact retained-packet reference."""
    from dataclasses import replace
    from src.media import crw_capture
    bundle, packet = varied_inputs(slug)
    event = replace(RegionalSSTAnomalyEvent(**bundle["raw_signal_dump"]), retained_packet=crw_capture.reference(packet))
    return story_bundle_snapshot(build_regional_sst_anomaly_bundle(event)), packet
