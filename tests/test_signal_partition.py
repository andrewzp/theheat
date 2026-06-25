"""US/non-US partition for THEHEAT_SIGNALS_PROVIDER=both.

GHCN owns the US (deep NOAA station coverage); Open-Meteo owns the rest of the
world (curated cities, incl. Europe). The two providers label the US
differently — cities.csv (Open-Meteo) uses "US"; GHCN uses the full
"United States" and bracketed-territory forms — so the predicate must catch
both, and only those.
"""

from src.data.open_meteo import CountryRecord, ExtremeSignalBundle
from src.orchestrator.signal_partition import is_us_location, partition_us_world


class TestIsUsLocation:
    def test_open_meteo_short_code_is_us(self):
        # cities.csv labels every US city "US".
        assert is_us_location("US") is True

    def test_ghcn_full_name_is_us(self):
        assert is_us_location("United States") is True

    def test_ghcn_territory_bracket_form_is_us(self):
        assert is_us_location("Northern Mariana Islands [United States]") is True

    def test_other_united_countries_are_not_us(self):
        # The predicate must not be fooled by "United" alone.
        assert is_us_location("United Kingdom") is False
        assert is_us_location("United Arab Emirates") is False

    def test_european_countries_are_not_us(self):
        for country in ("France", "Spain", "Italy", "Germany", "Portugal"):
            assert is_us_location(country) is False, country

    def test_empty_and_none_are_not_us(self):
        assert is_us_location("") is False
        assert is_us_location(None) is False


def _bundle(city: str, country: str) -> ExtremeSignalBundle:
    return ExtremeSignalBundle(city=city, country=country)


def _country_record(country: str) -> CountryRecord:
    return CountryRecord(
        country=country, kind="high", new_temp_c=45.0, peak_city="Peak",
        old_record_c=44.0, old_record_year=2003, old_record_city="Old",
        years_of_data=80, cities_sampled=7, event_id=f"country_high_{country}",
    )


class TestPartitionUsWorld:
    def test_us_from_ghcn_world_from_open_meteo(self):
        ghcn = [_bundle("Phoenix", "United States"), _bundle("Calgary", "Canada")]
        open_meteo = [_bundle("Dallas", "US"), _bundle("Seville", "Spain")]
        bundles, _ = partition_us_world(ghcn, [], open_meteo, [])
        labelled = [(b.city, b.country) for b in bundles]
        assert ("Phoenix", "United States") in labelled  # GHCN US kept
        assert ("Seville", "Spain") in labelled          # Open-Meteo non-US kept
        assert ("Calgary", "Canada") not in labelled     # GHCN non-US dropped
        assert ("Dallas", "US") not in labelled          # Open-Meteo US dropped
        assert len(bundles) == 2

    def test_country_records_follow_the_same_rule(self):
        ghcn_cr = [_country_record("United States"), _country_record("Canada")]
        open_meteo_cr = [_country_record("US"), _country_record("Italy")]
        _, records = partition_us_world([], ghcn_cr, [], open_meteo_cr)
        countries = [c.country for c in records]
        assert "United States" in countries  # GHCN US kept
        assert "Italy" in countries          # Open-Meteo non-US kept
        assert "Canada" not in countries     # GHCN non-US dropped
        assert "US" not in countries         # Open-Meteo US dropped

    def test_ghcn_us_ordered_before_open_meteo_world(self):
        ghcn = [_bundle("Miami", "United States")]
        open_meteo = [_bundle("Rome", "Italy")]
        bundles, _ = partition_us_world(ghcn, [], open_meteo, [])
        assert [b.city for b in bundles] == ["Miami", "Rome"]

    def test_empty_inputs(self):
        bundles, records = partition_us_world([], [], [], [])
        assert bundles == []
        assert records == []
