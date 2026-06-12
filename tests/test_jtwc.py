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
    def test_fetch_error_returns_empty_non_strict(self):
        responses.add(responses.GET, jtwc.JTWC_RSS_URL, status=500)
        assert jtwc.fetch_active_cyclones() == []
