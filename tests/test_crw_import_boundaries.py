"""The CRW region/bundle split keeps exact compatibility and a collector-free render closure.

``src.data.crw_regions`` and ``src.two_bot.intern.marine_crw`` hold the definitions the
sealed preview needs; the collector modules re-export the very same objects. The pinned
fingerprints were captured from invented inputs at the frozen P31 donor (a2396b7)
before the split, so any behavioural drift in bundles, registry URLs or tiers fails.
"""
from dataclasses import asdict
import json
import subprocess
import sys

from src.data import crw_regions, ocean_sst_anomaly
from src.editorial.revisions import fingerprint
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.two_bot.intern import marine, marine_crw
from tests.crw_graphic_helpers import graphic_inputs
from tests.gist_crw_helpers import varied_inputs

MOVED = ("ANOMALY_TIERS", "REGION_REGISTRY", "RegionDef", "RegionalSSTAnomalyEvent", "_ERDDAP_BASE", "_GRID_DEG",
         "_GRID_STRIDE", "_SST_ANOM_VAR", "_TARGET_DEG", "_build_url", "_detect_tier")
DONOR = {"uniform-last": "6fd79a7be9ee60ed661f16694e48f4a66dffa3279fc48489bcd4348f0ac3c757",
         "uniform-first": "1b72f3767fe7dfc898e1bb1e873e82e6d8ab008c295675239b792b6f6c928cfe",
         "varied-caribbean": "a7cd217f8cb8e35da6ac5243211b97eb3ba2febeb6df05e8cf1e0509b31a1de4",
         "varied-mediterranean": "f10de411ad10b8ecd556bc0a3934483ddb73e250394c08e60b91c59a0bd0fd53",
         "unqualified": "df5980550dd345266e9cff4f80b55a9f1750a8c57b0e8ca2adaa15ea68042880",
         "registry": "2fe665646b280e8e1db74d8c4b432160e7ad027db72335670d694c6488574f42"}


def test_collector_modules_re_export_the_same_objects():
    for name in MOVED:
        assert getattr(ocean_sst_anomaly, name) is getattr(crw_regions, name), name
    for name in ("build_regional_sst_anomaly_bundle", "legacy_regional_sst_anomaly_snapshot",
                 "_regional_sst_anomaly_bundle"):
        assert getattr(marine, name) is getattr(marine_crw, name), name


def test_bundles_registry_and_tiers_match_the_donor_exactly():
    o = ocean_sst_anomaly
    assert fingerprint(story_bundle_snapshot(graphic_inputs()[0])) == DONOR["uniform-last"]
    assert fingerprint(story_bundle_snapshot(graphic_inputs(region=o.REGION_REGISTRY[0])[0])) == DONOR["uniform-first"]
    for slug in ("caribbean", "mediterranean"):
        assert fingerprint(varied_inputs(slug)[0]) == DONOR["varied-" + slug]
    event = o.RegionalSSTAnomalyEvent("caribbean", "Caribbean Sea", "2026-06-14", 3.2, 1, 300,
                                      "sst_anom_caribbean_tier1_2026-06-14")
    assert fingerprint(asdict(marine.build_regional_sst_anomaly_bundle(event))) == DONOR["unqualified"]
    assert fingerprint(asdict(marine.legacy_regional_sst_anomaly_snapshot(event))) == DONOR["unqualified"]
    assert fingerprint([[r.slug, o._build_url(r)] for r in o.REGION_REGISTRY]) == DONOR["registry"]
    assert [o._detect_tier(v) for v in (2.4, 2.5, 3.5, 4.5, 9.0)] == [None, 1, 2, 3, 3]


def test_render_closure_loads_no_collector_or_database_module():
    # requests is already a locked native-closure dependency (src.data._http); not asserted here.
    code = ("import json, sys; import src.media.gist_crw_media, src.media.gist_published_media, "
            "src.media.gist_assets_postgres; print(json.dumps(sorted(sys.modules)))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    loaded = set(json.loads(result.stdout))
    forbidden = {"src.data.ocean_sst_anomaly", "src.two_bot.intern.marine", "src.orchestrator", "psycopg",
                 "xarray", "netCDF4", "numpy"}
    assert not loaded & forbidden, loaded & forbidden
