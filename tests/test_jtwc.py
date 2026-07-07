"""Tests for JTWC tropical-cyclone ingestion and parsing."""

from datetime import UTC, date, datetime, time, timedelta
from email.utils import format_datetime

import responses

from src.data import jtwc


RSS_NO_ACTIVE = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>No Active Tropical Warnings in the Northwest Pacific, North Indian Ocean, Central Pacific, Eastern Pacific, or Southern Hemisphere</title>
    <description>There are no active tropical warnings at this time.</description>
  </item>
</channel></rss>
"""


WARNING_TEXT = """
TROPICAL STORM 02W (MAWAR) WARNING NR 012
1. TROPICAL STORM 02W (MAWAR), LOCATED NEAR 12.5N 145.2E.
MAX SUSTAINED WINDS - 70 KT, GUSTS 85 KT.
MINIMUM CENTRAL PRESSURE 975 MB.
"""
FRESH_PUB_DATE = format_datetime(
    datetime.combine(date.today() - timedelta(days=1), time(1, 30), tzinfo=UTC)
)


class TestJTWCParsing:
    def test_parse_no_active_rss_returns_empty(self):
        assert jtwc.parse_rss(RSS_NO_ACTIVE) == []

    def test_parse_warning_text_normalizes_category_and_basin(self):
        advisory = jtwc.parse_warning_text(
            WARNING_TEXT,
            fallback_url="https://www.metoc.navy.mil/jtwc/products/wp0226web.txt",
            fallback_issued_at="Fri, 15 May 2026 01:30:02 +0000",
        )

        assert advisory is not None
        assert advisory.source == "jtwc"
        assert advisory.storm_id == "02W"
        assert advisory.storm_name == "Mawar"
        assert advisory.basin == "Western Pacific"
        assert advisory.wind_kt == 70
        assert advisory.pressure_mb == 975
        assert advisory.lat == 12.5
        assert advisory.lon == 145.2
        assert advisory.category == 1
        assert advisory.classification == "Tropical Storm"

    def test_parse_warning_text_maps_super_typhoon_to_saffir_simpson(self):
        text = WARNING_TEXT.replace("TROPICAL STORM", "SUPER TYPHOON").replace("70 KT", "140 KT")
        advisory = jtwc.parse_warning_text(
            text,
            fallback_issued_at="Fri, 15 May 2026 01:30:02 +0000",
        )

        assert advisory is not None
        assert advisory.category == 5
        assert advisory.classification == "Super Typhoon"

    @responses.activate
    def test_fetch_active_cyclones_follows_warning_links_from_rss(self):
        rss = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Western Pacific Tropical Warning</title>
            <link>https://s3.amazonaws.com/www.metoc.navy.mil/jtwc/jtwc.html</link>
            <description><![CDATA[
              <a href="https://www.metoc.navy.mil/jtwc/products/wp0226web.txt">WP0226 Warning</a>
            ]]></description>
            <pubDate>{FRESH_PUB_DATE}</pubDate>
          </item>
        </channel></rss>
        """
        responses.add(responses.GET, jtwc.JTWC_RSS_URL, body=rss, status=200)
        responses.add(
            responses.GET,
            "https://www.metoc.navy.mil/jtwc/products/wp0226web.txt",
            body=WARNING_TEXT,
            status=200,
        )

        advisories = jtwc.fetch_active_cyclones()

        assert len(advisories) == 1
        assert advisories[0].storm_name == "Mawar"

    @responses.activate
    def test_fetch_active_cyclones_tries_plain_rss_when_enhanced_feed_is_forbidden(self, capsys):
        rss = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Western Pacific Tropical Warning</title>
            <description><![CDATA[
              TROPICAL STORM 02W (MAWAR) WARNING NR 012
              MAX SUSTAINED WINDS - 70 KT, GUSTS 85 KT.
              LOCATED NEAR 12.5N 145.2E.
            ]]></description>
            <pubDate>{FRESH_PUB_DATE}</pubDate>
          </item>
        </channel></rss>
        """
        responses.add(
            responses.GET,
            jtwc.JTWC_RSS_URL,
            status=403,
            body="Forbidden",
            match=[responses.matchers.query_param_matcher({"layout": "enhanced"})],
        )
        responses.add(responses.GET, jtwc.JTWC_PLAIN_RSS_URL, body=rss, status=200)

        advisories = jtwc.fetch_active_cyclones(strict=True)

        assert "[jtwc] served by plain_rss" in capsys.readouterr().out
        assert len(advisories) == 1
        assert advisories[0].storm_name == "Mawar"
        assert advisories[0].source_leg == "plain_rss"

    @responses.activate
    def test_fetch_error_returns_empty_non_strict(self):
        responses.add(responses.GET, jtwc.JTWC_RSS_URL, status=500)
        assert jtwc.fetch_active_cyclones() == []


# ---------------------------------------------------------------------------
# Forecast-section parsing (#375 land-threat data half)
# ---------------------------------------------------------------------------

_JTWC_WARNING_FIXTURE = """\
SUPER TYPHOON 05W (BAVI) WARNING NR 024
...
WARNING POSITION:
060600Z --- NEAR 21.8N 126.9E
MOVEMENT PAST SIX HOURS - 310 DEGREES AT 08 KTS
MAX SUSTAINED WINDS - 135 KT, GUSTS 165 KT
...
FORECASTS:
12 HRS, VALID AT:
070000Z --- 22.9N 125.7E
MAX SUSTAINED WINDS - 130 KT, GUSTS 160 KT
...
24 HRS, VALID AT:
071200Z --- 23.9N 124.2E
MAX SUSTAINED WINDS - 120 KT, GUSTS 145 KT
...
48 HRS, VALID AT:
081200Z --- 25.4N 121.6E
MAX SUSTAINED WINDS - 95 KT, GUSTS 115 KT
"""


def test_parse_jtwc_forecast_sections_extracts_tau_position_wind():
    from src.data.cyclones import parse_jtwc_forecast_sections
    points = parse_jtwc_forecast_sections(_JTWC_WARNING_FIXTURE)
    assert [p.tau_h for p in points] == [12, 24, 48]
    assert points[0].lat == 22.9 and points[0].lon == 125.7
    assert points[0].max_wind_kt == 130
    # valid_at keeps the raw DDHHMMZ token; consumers resolve it against
    # the advisory's issued_at month/year at detection time.
    assert points[0].valid_at == "070000Z"
    assert points[2].lat == 25.4 and points[2].lon == 121.6


def test_parse_jtwc_forecast_sections_west_longitudes_negative():
    from src.data.cyclones import parse_jtwc_forecast_sections
    text = "FORECASTS:\n12 HRS, VALID AT:\n070000Z --- 22.9N 125.7W\nMAX SUSTAINED WINDS - 040 KT, GUSTS 050 KT\n"
    (p,) = parse_jtwc_forecast_sections(text)
    assert p.lon == -125.7


def test_parse_jtwc_forecast_sections_empty_on_no_forecast_block():
    from src.data.cyclones import parse_jtwc_forecast_sections
    assert parse_jtwc_forecast_sections("MAX SUSTAINED WINDS - 135 KT") == ()


_NHC_TCM_FIXTURE = """\
FORECAST VALID 08/0000Z 24.5N 122.0W
MAX WIND 105 KT...GUSTS 130 KT.

FORECAST VALID 08/1200Z 25.6N 123.4W
MAX WIND  95 KT...GUSTS 115 KT.
"""

# Real-product edge shapes (verified against the archived AL012025 TCM):
# a status suffix after the position and a dissipated entry with no
# position at all — the point still parses (wind absent) / is skipped.
_NHC_TCM_EDGE_FIXTURE = """\
FORECAST VALID 25/1200Z 39.6N  41.5W...POST-TROP/REMNT LOW
MAX WIND  30 KT...GUSTS  40 KT.

FORECAST VALID 26/0000Z...DISSIPATED
"""


def test_parse_nhc_forecast_advisory_extracts_points():
    from src.data.cyclones import parse_nhc_forecast_advisory
    points = parse_nhc_forecast_advisory(_NHC_TCM_FIXTURE)
    assert len(points) == 2
    assert points[0].valid_at == "08/0000Z"
    assert points[0].lat == 24.5 and points[0].lon == -122.0
    assert points[0].max_wind_kt == 105


def test_parse_nhc_forecast_advisory_handles_real_product_edges():
    from src.data.cyclones import parse_nhc_forecast_advisory
    points = parse_nhc_forecast_advisory(_NHC_TCM_EDGE_FIXTURE)
    # The dissipated line has no position — one point only.
    assert len(points) == 1
    assert points[0].lat == 39.6 and points[0].lon == -41.5


def test_parse_warning_text_populates_forecast_points():
    parsed = jtwc.parse_warning_text(_JTWC_WARNING_FIXTURE)
    assert parsed is not None
    assert len(parsed.forecast_points) == 3
    assert parsed.forecast_points[0].tau_h == 12


# ---------------------------------------------------------------------------
# detect_land_threats (#375)
# ---------------------------------------------------------------------------

def _advisory_with_forecast(points, *, wind_kt=135, storm_id="05W", name="BAVI"):
    from src.data.cyclones import CycloneAdvisory
    now = datetime.now(UTC)
    return CycloneAdvisory(
        source="jtwc", storm_id=storm_id, storm_name=name, basin="WP",
        advisory_number="024", issued_at=now.isoformat(), wind_kt=wind_kt,
        lat=21.8, lon=126.9, forecast_points=tuple(points),
    )


_TAIPEI = [{"city": "Taipei", "country": "Taiwan", "lat": "25.03", "lon": "121.57", "elevation_m": "9"}]


def test_land_threat_fires_when_forecast_point_near_landmass():
    from src.data.cyclones import ForecastPoint, detect_land_threats, event_key
    adv = _advisory_with_forecast([
        ForecastPoint(valid_at="ignored", lat=25.4, lon=121.6, max_wind_kt=95, tau_h=48),
    ])
    events = detect_land_threats([adv], drafted_pairs={}, cities=_TAIPEI,
                                 now=datetime.now(UTC))
    assert len(events) == 1
    ev = events[0]
    assert ev.landmass_country == "Taiwan"
    assert ev.nearest_city == "Taipei"
    assert ev.min_distance_nm < 30
    assert ev.closest_tau_h == 48
    assert ev.forecast_wind_kt_at_closest == 95
    assert ev.event_id == event_key("jtwc", "land_threat", "05W", "024", "taiwan")


def test_land_threat_skips_weak_storms():
    from src.data.cyclones import ForecastPoint, detect_land_threats
    adv = _advisory_with_forecast(
        [ForecastPoint(valid_at="x", lat=25.4, lon=121.6, tau_h=24)], wind_kt=45)
    assert detect_land_threats([adv], {}, _TAIPEI, now=datetime.now(UTC)) == []


def test_land_threat_skips_far_or_late_points():
    from src.data.cyclones import ForecastPoint, detect_land_threats
    adv = _advisory_with_forecast([
        ForecastPoint(valid_at="x", lat=5.0, lon=150.0, tau_h=24),   # far (> MAX_NM)
        ForecastPoint(valid_at="x", lat=25.4, lon=121.6, tau_h=96),  # late (> MAX_HOURS)
    ])
    assert detect_land_threats([adv], {}, _TAIPEI, now=datetime.now(UTC)) == []


def test_land_threat_one_shot_per_storm_landmass_pair():
    from src.data.cyclones import ForecastPoint, detect_land_threats
    adv = _advisory_with_forecast(
        [ForecastPoint(valid_at="x", lat=25.4, lon=121.6, tau_h=48)])
    drafted = {"jtwc:05w": ["taiwan"]}
    assert detect_land_threats([adv], drafted, _TAIPEI, now=datetime.now(UTC)) == []


def test_land_threat_picks_the_closest_qualifying_point():
    from src.data.cyclones import ForecastPoint, detect_land_threats
    adv = _advisory_with_forecast([
        ForecastPoint(valid_at="x", lat=23.9, lon=124.2, max_wind_kt=120, tau_h=24),
        ForecastPoint(valid_at="x", lat=25.4, lon=121.6, max_wind_kt=95, tau_h=48),
    ])
    (ev,) = detect_land_threats([adv], {}, _TAIPEI, now=datetime.now(UTC))
    assert ev.closest_tau_h == 48  # 25.4N/121.6E is nearer Taipei


def test_land_threat_nhc_token_resolution_within_window():
    # NHC points carry no tau; the DD/HHMMZ token resolves against issued_at.
    from src.data.cyclones import ForecastPoint, detect_land_threats
    now = datetime.now(UTC)
    in_window = (now + timedelta(hours=24)).strftime("%d/%H00Z")
    out_window = (now + timedelta(hours=120)).strftime("%d/%H00Z")
    adv_in = _advisory_with_forecast(
        [ForecastPoint(valid_at=in_window, lat=25.4, lon=121.6, max_wind_kt=90)])
    adv_out = _advisory_with_forecast(
        [ForecastPoint(valid_at=out_window, lat=25.4, lon=121.6, max_wind_kt=90)],
        storm_id="06W")
    events = detect_land_threats([adv_in, adv_out], {}, _TAIPEI, now=now)
    assert len(events) == 1
    assert events[0].storm_id == "05W"


def test_land_threat_unparsable_token_never_mints():
    # Fail-closed: an unparsable valid_at (no tau) never produces an event.
    from src.data.cyclones import ForecastPoint, detect_land_threats
    adv = _advisory_with_forecast(
        [ForecastPoint(valid_at="garbage", lat=25.4, lon=121.6)])
    assert detect_land_threats([adv], {}, _TAIPEI, now=datetime.now(UTC)) == []
