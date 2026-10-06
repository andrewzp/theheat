"""Invented source-shaped regional values, not retained production observations."""

from src.data import crw_contract as source
from src.data.ocean_sst_anomaly import REGION_REGISTRY, RegionalSSTAnomalyEvent, _build_url
from src.two_bot.intern.marine import build_regional_sst_anomaly_bundle
from tests.crw_fixtures import DAY, RETRIEVED, csv_body, metadata_body, metadata_receipt


def graphic_inputs(value=3.6, selected=None, region=None):
    region = region or REGION_REGISTRY[-1]
    raw = csv_body(region, value=value, selected=selected)
    sample = source.decode_csv(raw.decode(), region)
    # Fixtures stipulate a uniform valid value; nonuniform arithmetic has its own test.
    tier = 3 if value >= 4.5 else 2 if value >= 3.5 else 1
    p = source.provenance(
        body=raw,
        url=_build_url(region),
        retrieved_at=RETRIEVED,
        timestamp=f"{DAY}T12:00:00Z",
        region=region,
        mean=value,
        valid_cells=len(sample.cells),
        total_cells=sample.total_cells,
        sampled_bounds=sample.sampled_bounds,
        leg="coastwatch_erddap",
        metadata=metadata_receipt(),
    )
    bundle = build_regional_sst_anomaly_bundle(
        RegionalSSTAnomalyEvent(
            region.slug,
            region.display_name,
            DAY,
            value,
            tier,
            len(sample.cells),
            f"sst_anom_{region.slug}_tier{tier}_{DAY}",
            provenance=p,
        )
    )
    packet = {
        "schema_version": 1,
        "csv_utf8": raw.decode(),
        "metadata_utf8": metadata_body().decode(),
        "csv_retrieved_at": RETRIEVED,
        "metadata_retrieved_at": RETRIEVED,
    }
    return bundle, packet
