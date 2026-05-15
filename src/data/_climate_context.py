"""Curated geographic-climate context for story bundles.

The writer can only use system clauses that the fact-checker can verify from the
bundle. This module keeps those clauses deterministic: no LLM lookups, no live
geocoding, just source-backed climate regions ordered from specific to broad.

Bounding boxes are intentionally coarse. First match wins, so put smaller or more
mechanistic regions before larger climate belts when they overlap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClimateContext:
    region_climate_system: str
    climate_mechanism_note: str | None = None
    local_topography_note: str | None = None
    season_context: str | None = None


@dataclass(frozen=True)
class ClimateContextRegion:
    key: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    sample_lat: float
    sample_lon: float
    context: ClimateContext
    source_title: str
    source_url: str
    categories: tuple[str, ...] = ()

    def contains(self, lat: float, lon: float) -> bool:
        lat_match = self.lat_min <= lat <= self.lat_max
        if self.lon_min <= self.lon_max:
            lon_match = self.lon_min <= lon <= self.lon_max
        else:
            # Dateline-crossing boxes, e.g. 160E to 130W.
            lon_match = lon >= self.lon_min or lon <= self.lon_max
        return lat_match and lon_match

    def matches_category(self, category: str | None) -> bool:
        return category is None or not self.categories or category in self.categories


CLIMATE_CONTEXT_REGIONS: tuple[ClimateContextRegion, ...] = (
    ClimateContextRegion(
        key="androscoggin_valley",
        lat_min=43.5,
        lat_max=45.3,
        lon_min=-72.0,
        lon_max=-69.0,
        sample_lat=44.4,
        sample_lon=-70.8,
        context=ClimateContext(
            region_climate_system="the northern New England mountain-valley climate",
            local_topography_note="the Androscoggin River valley sits near the White Mountains",
            climate_mechanism_note="cold air can drain into sheltered valleys from nearby high terrain",
        ),
        source_title="Androscoggin River; White Mountains",
        source_url="https://en.wikipedia.org/wiki/Androscoggin_River",
    ),
    ClimateContextRegion(
        key="florida_sea_breeze_zone",
        lat_min=25.0,
        lat_max=31.0,
        lon_min=-82.7,
        lon_max=-80.0,
        sample_lat=28.2,
        sample_lon=-81.1,
        context=ClimateContext(
            region_climate_system="the Florida sea-breeze zone",
            climate_mechanism_note="Atlantic and Gulf sea breezes focus humid afternoon convection",
            season_context="warm-season sea-breeze thunderstorm regime",
        ),
        source_title="Climate of Florida",
        source_url="https://en.wikipedia.org/wiki/Climate_of_Florida",
    ),
    ClimateContextRegion(
        key="great_lakes_lake_effect_belt",
        lat_min=41.0,
        lat_max=47.5,
        lon_min=-93.0,
        lon_max=-75.0,
        sample_lat=42.9,
        sample_lon=-78.9,
        context=ClimateContext(
            region_climate_system="the Great Lakes lake-effect belt",
            climate_mechanism_note="open lake water can feed lake-effect snow and cold-season moisture",
            local_topography_note="Great Lakes shorelines focus local snow belts downwind of the lakes",
        ),
        source_title="Lake-effect snow",
        source_url="https://en.wikipedia.org/wiki/Lake-effect_snow",
        categories=("cold", "low", "snow"),
    ),
    ClimateContextRegion(
        key="cascade_rain_shadow",
        lat_min=43.0,
        lat_max=49.0,
        lon_min=-122.0,
        lon_max=-116.0,
        sample_lat=46.2,
        sample_lon=-119.0,
        context=ClimateContext(
            region_climate_system="the Cascade rain shadow",
            climate_mechanism_note="Pacific air loses moisture over the Cascades before reaching the interior Northwest",
            local_topography_note="the Cascade Range separates the wet coast from the drier inland basin",
        ),
        source_title="Cascade Range; rain shadow",
        source_url="https://en.wikipedia.org/wiki/Cascade_Range",
    ),
    ClimateContextRegion(
        key="california_central_valley",
        lat_min=35.0,
        lat_max=40.5,
        lon_min=-123.0,
        lon_max=-118.0,
        sample_lat=37.5,
        sample_lon=-120.5,
        context=ClimateContext(
            region_climate_system="the California Central Valley",
            climate_mechanism_note="a hot inland valley climate sits between the Coast Ranges and Sierra Nevada",
            local_topography_note="the Coast Ranges and Sierra Nevada frame the valley floor",
            season_context="Mediterranean summer-dry seasonality",
        ),
        source_title="Central Valley (California)",
        source_url="https://en.wikipedia.org/wiki/Central_Valley_(California)",
    ),
    ClimateContextRegion(
        key="pacific_northwest_marine_layer",
        lat_min=42.0,
        lat_max=49.0,
        lon_min=-125.0,
        lon_max=-122.0,
        sample_lat=45.6,
        sample_lon=-123.0,
        context=ClimateContext(
            region_climate_system="the Pacific Northwest marine layer",
            climate_mechanism_note="cool Pacific air and marine stratus moderate coastal heat",
            season_context="summer marine-layer regime",
        ),
        source_title="Pacific Northwest; marine layer",
        source_url="https://en.wikipedia.org/wiki/Pacific_Northwest",
    ),
    ClimateContextRegion(
        key="sonoran_desert",
        lat_min=28.0,
        lat_max=36.0,
        lon_min=-116.0,
        lon_max=-108.0,
        sample_lat=33.5,
        sample_lon=-112.1,
        context=ClimateContext(
            region_climate_system="the Sonoran Desert",
            climate_mechanism_note="subtropical desert heat builds across the lower Colorado basin",
            season_context="North American monsoon influence in late summer",
        ),
        source_title="Sonoran Desert",
        source_url="https://en.wikipedia.org/wiki/Sonoran_Desert",
    ),
    ClimateContextRegion(
        key="colorado_plateau",
        lat_min=35.0,
        lat_max=39.5,
        lon_min=-113.5,
        lon_max=-106.0,
        sample_lat=36.8,
        sample_lon=-111.9,
        context=ClimateContext(
            region_climate_system="the Colorado Plateau",
            climate_mechanism_note="high-elevation aridity sharpens desert temperature swings",
            local_topography_note="plateaus and canyon country sit between the Rockies and Basin and Range",
        ),
        source_title="Colorado Plateau",
        source_url="https://en.wikipedia.org/wiki/Colorado_Plateau",
    ),
    ClimateContextRegion(
        key="chihuahuan_desert",
        lat_min=25.0,
        lat_max=35.0,
        lon_min=-108.0,
        lon_max=-100.0,
        sample_lat=31.8,
        sample_lon=-106.4,
        context=ClimateContext(
            region_climate_system="the Chihuahuan Desert",
            climate_mechanism_note="continental desert air drives large heat and dryness swings",
        ),
        source_title="Chihuahuan Desert",
        source_url="https://en.wikipedia.org/wiki/Chihuahuan_Desert",
    ),
    ClimateContextRegion(
        key="high_plains",
        lat_min=32.0,
        lat_max=49.0,
        lon_min=-104.0,
        lon_max=-96.0,
        sample_lat=39.7,
        sample_lon=-101.0,
        context=ClimateContext(
            region_climate_system="the High Plains",
            climate_mechanism_note="semi-arid continental air and dryline gradients shape Plains heat and storms",
            local_topography_note="the terrain slopes eastward from the Rocky Mountain front",
        ),
        source_title="High Plains (United States)",
        source_url="https://en.wikipedia.org/wiki/High_Plains_(United_States)",
    ),
    ClimateContextRegion(
        key="gulf_coast_humid_subtropics",
        lat_min=25.0,
        lat_max=31.5,
        lon_min=-98.0,
        lon_max=-80.0,
        sample_lat=29.8,
        sample_lon=-90.0,
        context=ClimateContext(
            region_climate_system="the Gulf Coast humid subtropical belt",
            climate_mechanism_note="warm Gulf moisture feeds humid heat and heavy-rain setups",
            season_context="humid subtropical warm season",
        ),
        source_title="Climate of the United States",
        source_url="https://en.wikipedia.org/wiki/Climate_of_the_United_States",
    ),
    ClimateContextRegion(
        key="atlantic_coastal_plain",
        lat_min=30.0,
        lat_max=39.5,
        lon_min=-81.5,
        lon_max=-74.0,
        sample_lat=35.0,
        sample_lon=-78.0,
        context=ClimateContext(
            region_climate_system="the Atlantic Coastal Plain",
            climate_mechanism_note="low coastal terrain and Atlantic moisture shape humid heat and storms",
        ),
        source_title="Atlantic coastal plain",
        source_url="https://en.wikipedia.org/wiki/Atlantic_coastal_plain",
    ),
    ClimateContextRegion(
        key="western_pacific_warm_pool",
        lat_min=0.0,
        lat_max=15.0,
        lon_min=120.0,
        lon_max=160.0,
        sample_lat=7.4,
        sample_lon=151.8,
        context=ClimateContext(
            region_climate_system="the western Pacific warm pool",
            climate_mechanism_note="persistently warm tropical ocean water anchors deep convection",
            season_context="tropical warm-pool convection regime",
        ),
        source_title="Tropical Warm Pool",
        source_url="https://en.wikipedia.org/wiki/Tropical_Warm_Pool",
    ),
    ClimateContextRegion(
        key="south_pacific_convergence_zone",
        lat_min=-25.0,
        lat_max=-5.0,
        lon_min=160.0,
        lon_max=-130.0,
        sample_lat=-15.0,
        sample_lon=-170.0,
        context=ClimateContext(
            region_climate_system="the South Pacific Convergence Zone",
            climate_mechanism_note="a diagonal band of low-level convergence and tropical rainfall extends southeast from the warm pool",
        ),
        source_title="South Pacific convergence zone",
        source_url="https://en.wikipedia.org/wiki/South_Pacific_convergence_zone",
    ),
    ClimateContextRegion(
        key="atlantic_itcz",
        lat_min=5.0,
        lat_max=10.0,
        lon_min=-50.0,
        lon_max=0.0,
        sample_lat=7.0,
        sample_lon=-25.0,
        context=ClimateContext(
            region_climate_system="the Atlantic ITCZ",
            climate_mechanism_note="trade winds converge near the equator and focus tropical rainfall",
            season_context="tropical convergence-zone seasonality",
        ),
        source_title="Intertropical Convergence Zone",
        source_url="https://en.wikipedia.org/wiki/Intertropical_Convergence_Zone",
    ),
    ClimateContextRegion(
        key="sahel",
        lat_min=12.0,
        lat_max=18.0,
        lon_min=-18.0,
        lon_max=30.0,
        sample_lat=13.5,
        sample_lon=-4.2,
        context=ClimateContext(
            region_climate_system="the Sahel",
            climate_mechanism_note="a semi-arid transition zone sits between the Sahara and wetter savanna",
            season_context="sharp wet-dry seasonal transition",
        ),
        source_title="Sahel",
        source_url="https://en.wikipedia.org/wiki/Sahel",
    ),
    ClimateContextRegion(
        key="west_african_monsoon_belt",
        lat_min=5.0,
        lat_max=15.0,
        lon_min=-20.0,
        lon_max=15.0,
        sample_lat=11.0,
        sample_lon=5.0,
        context=ClimateContext(
            region_climate_system="the West African monsoon belt",
            climate_mechanism_note="seasonal monsoon flow controls the north-south rain gradient",
            season_context="West African monsoon seasonality",
        ),
        source_title="West African Monsoon",
        source_url="https://en.wikipedia.org/wiki/West_African_Monsoon",
    ),
    ClimateContextRegion(
        key="sahara",
        lat_min=18.0,
        lat_max=30.0,
        lon_min=-17.0,
        lon_max=35.0,
        sample_lat=23.0,
        sample_lon=12.0,
        context=ClimateContext(
            region_climate_system="the Sahara",
            climate_mechanism_note="subtropical high pressure helps sustain extreme desert aridity",
        ),
        source_title="Sahara",
        source_url="https://en.wikipedia.org/wiki/Sahara",
    ),
    ClimateContextRegion(
        key="ethiopian_highlands",
        lat_min=6.0,
        lat_max=15.0,
        lon_min=34.0,
        lon_max=42.5,
        sample_lat=9.0,
        sample_lon=38.7,
        context=ClimateContext(
            region_climate_system="the Ethiopian Highlands",
            climate_mechanism_note="high terrain shapes local rainfall and temperature gradients",
            local_topography_note="the highlands rise sharply above the surrounding lowlands",
        ),
        source_title="Ethiopian Highlands",
        source_url="https://en.wikipedia.org/wiki/Ethiopian_Highlands",
    ),
    ClimateContextRegion(
        key="congo_basin",
        lat_min=-7.0,
        lat_max=5.0,
        lon_min=12.0,
        lon_max=30.0,
        sample_lat=-2.0,
        sample_lon=23.0,
        context=ClimateContext(
            region_climate_system="the Congo Basin rainforest",
            climate_mechanism_note="deep tropical forest and equatorial moisture support persistent convection",
        ),
        source_title="Congo Basin",
        source_url="https://en.wikipedia.org/wiki/Congo_Basin",
    ),
    ClimateContextRegion(
        key="mediterranean_basin",
        lat_min=30.0,
        lat_max=45.0,
        lon_min=-10.0,
        lon_max=40.0,
        sample_lat=38.0,
        sample_lon=15.0,
        context=ClimateContext(
            region_climate_system="the Mediterranean basin",
            climate_mechanism_note="summer subtropical high pressure favors dry heat around the basin",
            season_context="Mediterranean summer-dry climate",
        ),
        source_title="Mediterranean Basin",
        source_url="https://en.wikipedia.org/wiki/Mediterranean_Basin",
    ),
    ClimateContextRegion(
        key="amazon_basin",
        lat_min=-10.0,
        lat_max=5.0,
        lon_min=-75.0,
        lon_max=-50.0,
        sample_lat=-3.0,
        sample_lon=-60.0,
        context=ClimateContext(
            region_climate_system="the Amazon basin",
            climate_mechanism_note="tropical rainforest moisture recycles heat into deep convection",
        ),
        source_title="Amazon basin",
        source_url="https://en.wikipedia.org/wiki/Amazon_basin",
    ),
    ClimateContextRegion(
        key="cerrado",
        lat_min=-25.0,
        lat_max=-5.0,
        lon_min=-60.0,
        lon_max=-40.0,
        sample_lat=-15.5,
        sample_lon=-47.8,
        context=ClimateContext(
            region_climate_system="the Cerrado savanna",
            climate_mechanism_note="tropical savanna seasonality alternates wet growth with dry-season fire weather",
            season_context="tropical savanna wet-dry cycle",
        ),
        source_title="Cerrado",
        source_url="https://en.wikipedia.org/wiki/Cerrado",
    ),
    ClimateContextRegion(
        key="andean_rain_shadow_patagonia",
        lat_min=-45.0,
        lat_max=-35.0,
        lon_min=-75.0,
        lon_max=-65.0,
        sample_lat=-41.0,
        sample_lon=-70.0,
        context=ClimateContext(
            region_climate_system="the Patagonian Andean rain shadow",
            climate_mechanism_note="westerly air loses moisture over the Andes before reaching eastern Patagonia",
            local_topography_note="the Andes separate wet Pacific slopes from dry leeward Patagonia",
        ),
        source_title="Patagonian Desert",
        source_url="https://en.wikipedia.org/wiki/Patagonian_Desert",
    ),
    ClimateContextRegion(
        key="great_barrier_reef",
        lat_min=-24.5,
        lat_max=-10.0,
        lon_min=142.0,
        lon_max=154.0,
        sample_lat=-18.3,
        sample_lon=147.7,
        context=ClimateContext(
            region_climate_system="the Great Barrier Reef shelf lagoon",
            climate_mechanism_note="a shallow tropical shelf reef system is exposed to marine heat stress",
            season_context="southern-hemisphere warm-season reef heat-stress regime",
        ),
        source_title="Great Barrier Reef",
        source_url="https://en.wikipedia.org/wiki/Great_Barrier_Reef",
        categories=("coral",),
    ),
    ClimateContextRegion(
        key="pampas",
        lat_min=-40.0,
        lat_max=-30.0,
        lon_min=-65.0,
        lon_max=-55.0,
        sample_lat=-34.6,
        sample_lon=-58.4,
        context=ClimateContext(
            region_climate_system="the Pampas grassland",
            climate_mechanism_note="temperate grassland and humid subtropical air shape strong frontal swings",
        ),
        source_title="Pampas",
        source_url="https://en.wikipedia.org/wiki/Pampas",
    ),
    ClimateContextRegion(
        key="atacama_desert",
        lat_min=-28.0,
        lat_max=-18.0,
        lon_min=-75.0,
        lon_max=-68.0,
        sample_lat=-23.5,
        sample_lon=-70.3,
        context=ClimateContext(
            region_climate_system="the Atacama Desert",
            climate_mechanism_note="coastal cold water and subtropical subsidence help sustain extreme aridity",
            local_topography_note="the Andes block moisture from the interior side",
        ),
        source_title="Atacama Desert",
        source_url="https://en.wikipedia.org/wiki/Atacama_Desert",
    ),
    ClimateContextRegion(
        key="australian_monsoon_tropics",
        lat_min=-20.0,
        lat_max=-10.0,
        lon_min=120.0,
        lon_max=145.0,
        sample_lat=-12.5,
        sample_lon=131.0,
        context=ClimateContext(
            region_climate_system="the Australian monsoon tropics",
            climate_mechanism_note="seasonal monsoon flow drives the wet-dry split across northern Australia",
            season_context="Australian tropical monsoon seasonality",
        ),
        source_title="Australian monsoon",
        source_url="https://en.wikipedia.org/wiki/Australian_monsoon",
    ),
    ClimateContextRegion(
        key="australian_outback",
        lat_min=-30.0,
        lat_max=-20.0,
        lon_min=120.0,
        lon_max=145.0,
        sample_lat=-25.0,
        sample_lon=133.0,
        context=ClimateContext(
            region_climate_system="the Australian outback",
            climate_mechanism_note="continental aridity lets inland heat build far from ocean moderation",
        ),
        source_title="Outback",
        source_url="https://en.wikipedia.org/wiki/Outback",
    ),
    ClimateContextRegion(
        key="great_dividing_range",
        lat_min=-38.0,
        lat_max=-25.0,
        lon_min=145.0,
        lon_max=153.5,
        sample_lat=-33.5,
        sample_lon=150.5,
        context=ClimateContext(
            region_climate_system="the Great Dividing Range",
            climate_mechanism_note="eastern Australian high terrain shapes coastal rainfall and inland rain shadows",
            local_topography_note="the range separates the coastal plain from drier inland basins",
        ),
        source_title="Great Dividing Range",
        source_url="https://en.wikipedia.org/wiki/Great_Dividing_Range",
    ),
    ClimateContextRegion(
        key="hindu_kush_rain_shadow",
        lat_min=30.0,
        lat_max=37.0,
        lon_min=65.0,
        lon_max=75.0,
        sample_lat=34.5,
        sample_lon=69.0,
        context=ClimateContext(
            region_climate_system="the Hindu Kush rain shadow",
            climate_mechanism_note="high mountains split moist air from dry interior basins",
            local_topography_note="the Hindu Kush creates sharp leeward dryness",
        ),
        source_title="Hindu Kush",
        source_url="https://en.wikipedia.org/wiki/Hindu_Kush",
    ),
    ClimateContextRegion(
        key="indo_gangetic_plain",
        lat_min=22.0,
        lat_max=30.5,
        lon_min=72.0,
        lon_max=90.0,
        sample_lat=26.8,
        sample_lon=80.9,
        context=ClimateContext(
            region_climate_system="the Indo-Gangetic Plain",
            climate_mechanism_note="a lowland monsoon plain traps heat, humidity, and winter inversions",
            season_context="South Asian monsoon seasonality",
        ),
        source_title="Indo-Gangetic Plain",
        source_url="https://en.wikipedia.org/wiki/Indo-Gangetic_Plain",
    ),
    ClimateContextRegion(
        key="thar_desert",
        lat_min=24.0,
        lat_max=30.0,
        lon_min=68.0,
        lon_max=76.0,
        sample_lat=27.0,
        sample_lon=71.0,
        context=ClimateContext(
            region_climate_system="the Thar Desert",
            climate_mechanism_note="arid subtropical desert heat sits on the edge of the South Asian monsoon",
            season_context="monsoon-edge desert seasonality",
        ),
        source_title="Thar Desert",
        source_url="https://en.wikipedia.org/wiki/Thar_Desert",
    ),
    ClimateContextRegion(
        key="tibetan_plateau",
        lat_min=28.0,
        lat_max=38.0,
        lon_min=78.0,
        lon_max=100.0,
        sample_lat=31.0,
        sample_lon=88.0,
        context=ClimateContext(
            region_climate_system="the Tibetan Plateau",
            climate_mechanism_note="high elevation controls strong temperature swings and monsoon circulation",
            local_topography_note="the plateau is one of the world's highest broad uplands",
        ),
        source_title="Tibetan Plateau",
        source_url="https://en.wikipedia.org/wiki/Tibetan_Plateau",
    ),
    ClimateContextRegion(
        key="eastern_mongolian_steppe",
        lat_min=43.0,
        lat_max=50.0,
        lon_min=100.0,
        lon_max=125.0,
        sample_lat=46.5,
        sample_lon=114.0,
        context=ClimateContext(
            region_climate_system="the eastern Mongolian steppe",
            climate_mechanism_note="continental grassland climate brings dry air and large temperature swings",
            season_context="temperate steppe fire-weather seasonality",
        ),
        source_title="Mongolian-Manchurian grassland",
        source_url="https://en.wikipedia.org/wiki/Mongolian%E2%80%93Manchurian_grassland",
    ),
    ClimateContextRegion(
        key="siberian_continental_cold_pool",
        lat_min=50.0,
        lat_max=65.0,
        lon_min=60.0,
        lon_max=120.0,
        sample_lat=62.0,
        sample_lon=92.0,
        context=ClimateContext(
            region_climate_system="the Siberian continental interior",
            climate_mechanism_note="far-inland continental air supports some of the planet's strongest cold-season extremes",
        ),
        source_title="Siberia; subarctic climate",
        source_url="https://en.wikipedia.org/wiki/Siberia",
        categories=("cold", "low"),
    ),
    ClimateContextRegion(
        key="persian_gulf_heat_basin",
        lat_min=24.0,
        lat_max=31.0,
        lon_min=48.0,
        lon_max=57.0,
        sample_lat=26.5,
        sample_lon=51.5,
        context=ClimateContext(
            region_climate_system="the Persian Gulf heat basin",
            climate_mechanism_note="shallow Gulf waters add humidity to extreme desert heat",
        ),
        source_title="Persian Gulf; climate of the Persian Gulf region",
        source_url="https://en.wikipedia.org/wiki/Persian_Gulf",
    ),
    ClimateContextRegion(
        key="arabian_desert",
        lat_min=16.0,
        lat_max=30.0,
        lon_min=35.0,
        lon_max=60.0,
        sample_lat=23.0,
        sample_lon=45.0,
        context=ClimateContext(
            region_climate_system="the Arabian Desert",
            climate_mechanism_note="subtropical desert air and continental interiors drive severe heat",
        ),
        source_title="Arabian Desert",
        source_url="https://en.wikipedia.org/wiki/Arabian_Desert",
    ),
    ClimateContextRegion(
        key="maritime_continent",
        lat_min=-10.0,
        lat_max=10.0,
        lon_min=95.0,
        lon_max=140.0,
        sample_lat=-2.0,
        sample_lon=118.0,
        context=ClimateContext(
            region_climate_system="the Maritime Continent",
            climate_mechanism_note="warm seas and island topography fuel tropical convection",
        ),
        source_title="Maritime Continent",
        source_url="https://en.wikipedia.org/wiki/Maritime_Continent",
    ),
    ClimateContextRegion(
        key="central_american_dry_corridor",
        lat_min=10.0,
        lat_max=16.0,
        lon_min=-92.0,
        lon_max=-83.0,
        sample_lat=13.7,
        sample_lon=-88.9,
        context=ClimateContext(
            region_climate_system="the Central American Dry Corridor",
            climate_mechanism_note="a seasonally dry Pacific-side corridor is exposed to drought and fire stress",
            season_context="Pacific-side wet-dry seasonality",
        ),
        source_title="Central American dry corridor",
        source_url="https://en.wikipedia.org/wiki/Central_American_dry_corridor",
    ),
    ClimateContextRegion(
        key="caribbean_warm_pool",
        lat_min=10.0,
        lat_max=25.0,
        lon_min=-90.0,
        lon_max=-60.0,
        sample_lat=18.0,
        sample_lon=-75.0,
        context=ClimateContext(
            region_climate_system="the Caribbean warm pool",
            climate_mechanism_note="warm tropical waters feed humidity, heavy rain, and cyclone energy",
            season_context="Atlantic tropical warm-season regime",
        ),
        source_title="Atlantic Warm Pool",
        source_url="https://en.wikipedia.org/wiki/Atlantic_Warm_Pool",
    ),
)


def _normalize_lon(lon: float) -> float:
    """Normalize longitude to the conventional -180..180 range."""

    if -180.0 <= lon <= 180.0:
        return lon
    normalized = ((lon + 180.0) % 360.0) - 180.0
    return 180.0 if normalized == -180.0 and lon > 0 else normalized


def local_climate_context(
    lat: float,
    lon: float,
    category: str | None = None,
) -> ClimateContext | None:
    """Return deterministic climate context for a point, or ``None``.

    ``category`` is a conservative filter for future callers. A region without
    categories applies to all signals; a category-specific region only applies
    when the caller's category matches exactly.
    """

    if not -90.0 <= lat <= 90.0:
        return None
    lon = _normalize_lon(lon)
    normalized_category = category.strip().lower() if category else None

    for region in CLIMATE_CONTEXT_REGIONS:
        if region.contains(lat, lon) and region.matches_category(normalized_category):
            return region.context
    return None
