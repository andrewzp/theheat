"""Tests for src/data/ghcn_format.py.

Uses vendored fixture files in tests/fixtures/ghcn/ to avoid any network
calls. The fixture USW00023183_excerpt.dly contains synthetic data modelled
on Phoenix Sky Harbor format with an engineered 2023-07-16 all-time TMAX
record of 52.2°C (raw 522 tenths-of-°C).

Station context:
  USW00023183  Phoenix Sky Harbor, AZ, USA
  1933 data    baseline-era temps (~36-46°C TMAX in summer)
  2023 data    recent period with engineered record on 2023-07-16

Fixture line format: 269 chars per line.
  header (21):  station_id(11) year(4) month(2) element(4)
  31 days (248): each 8 chars: VALUE(5) MFLAG(1) QFLAG(1) SFLAG(1)
  QFLAG = ' ' (space) means valid; any non-space = quality failure (excluded).
"""

from __future__ import annotations

import io
import tarfile
import textwrap
from datetime import date
from pathlib import Path

import pytest

from src.data.ghcn_format import (
    DailyObs,
    ElementInventory,
    StationMeta,
    StationThresholds,
    compute_thresholds,
    parse_countries_file,
    parse_dly_text,
    parse_superghcnd_diff_bytes,
    parse_superghcnd_diff_records_bytes,
    parse_inventory_file,
    parse_stations_file,
    parse_superghcnd_diff_text,
    update_thresholds_with_obs,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ghcn"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_dly_line(
    station_id: str,
    year: int,
    month: int,
    element: str,
    day_values: list[int | None],
) -> str:
    """Build a valid 269-char .dly record line for testing.

    day_values: list of int (tenths-of-°C) or None for missing.
    Uses mflag=' ', qflag=' ' (valid), sflag='6'.
    """
    header = f"{station_id}{year:04d}{month:02d}{element}"
    assert len(header) == 21
    days: list[str] = []
    for i in range(31):
        if i < len(day_values) and day_values[i] is not None:
            v = day_values[i]
            days.append(f"{v:5d}  6")  # value + mflag=' ' + qflag=' ' + sflag='6'
        else:
            days.append("-9999   ")   # missing + blank flags
    line = header + "".join(days)
    assert len(line) == 269
    return line


# ---------------------------------------------------------------------------
# parse_stations_file
# ---------------------------------------------------------------------------

# Proper GHCN fixed-width format (1 separator space between each field):
#  ID(11) sp LAT(8) sp LON(9) sp ELEV(6) sp STATE(2) sp NAME(30) sp GSN(3) sp HCN(3) sp WMO(5)
# Generated via: ghcn_station_line() helper matching actual NCEI column layout.
SAMPLE_STATIONS_TXT = (
    "USW00023183  33.4300 -112.0100  337.1 AZ PHOENIX SKY HARBOR INTL AP     GSN HCN 72278\n"
    "RSM00024266  67.5500  133.3800  137.0    VERKHOYANSK                    GSN     23822\n"
    "USC00042319  36.4600 -116.8700  -59.1 CA DEATH VALLEY NP                    HCN      \n"
    "IN019180300  27.1100   72.4200  234.0    PHALODI                                     \n"
)


def test_parse_stations_file_count():
    stations = parse_stations_file(SAMPLE_STATIONS_TXT)
    assert len(stations) == 4


def test_parse_stations_file_phoenix():
    stations = parse_stations_file(SAMPLE_STATIONS_TXT)
    phx = next(s for s in stations if s.station_id == "USW00023183")
    assert phx.lat == pytest.approx(33.43, abs=0.01)
    assert phx.lon == pytest.approx(-112.01, abs=0.01)
    assert phx.elevation_m == pytest.approx(337.1, abs=0.1)
    assert phx.state == "AZ"
    assert "PHOENIX" in phx.name
    assert phx.gsn_flag == "GSN"
    assert phx.hcn_crn_flag == "HCN"
    assert phx.wmo_id == "72278"


def test_parse_stations_file_verkhoyansk():
    stations = parse_stations_file(SAMPLE_STATIONS_TXT)
    vrk = next(s for s in stations if s.station_id == "RSM00024266")
    assert vrk.lat == pytest.approx(67.55, abs=0.01)
    assert vrk.country_code_inferred() == "RS"  # first 2 chars of station_id
    assert vrk.name == "VERKHOYANSK"
    assert vrk.state == ""


def test_parse_stations_file_death_valley_negative_elevation():
    stations = parse_stations_file(SAMPLE_STATIONS_TXT)
    dv = next(s for s in stations if s.station_id == "USC00042319")
    assert dv.elevation_m == pytest.approx(-59.1, abs=0.1)
    assert dv.hcn_crn_flag == "HCN"
    assert dv.wmo_id == ""


def test_parse_stations_file_empty():
    assert parse_stations_file("") == []


def test_parse_stations_file_skips_malformed():
    bad = "TOOSHORT\n"
    result = parse_stations_file(bad)
    assert result == []


# ---------------------------------------------------------------------------
# parse_inventory_file
# ---------------------------------------------------------------------------

SAMPLE_INVENTORY_TXT = textwrap.dedent("""\
USW00023183  33.4300 -112.0100 TMAX 1933 2026
USW00023183  33.4300 -112.0100 TMIN 1933 2026
USW00023183  33.4300 -112.0100 PRCP 1933 2026
RSM00024266  67.5500  133.3800 TMAX 1895 2025
RSM00024266  67.5500  133.3800 TMIN 1895 2025
USC00042319  36.4600 -116.8700 TMAX 1911 2026
""")


def test_parse_inventory_file_count():
    rows = parse_inventory_file(SAMPLE_INVENTORY_TXT)
    assert len(rows) == 6


def test_parse_inventory_file_phoenix_tmax():
    rows = parse_inventory_file(SAMPLE_INVENTORY_TXT)
    phx_tmax = next(r for r in rows if r.station_id == "USW00023183" and r.element == "TMAX")
    assert phx_tmax.first_year == 1933
    assert phx_tmax.last_year == 2026


def test_parse_inventory_file_verkhoyansk_old_record():
    rows = parse_inventory_file(SAMPLE_INVENTORY_TXT)
    vrk = next(r for r in rows if r.station_id == "RSM00024266" and r.element == "TMAX")
    assert vrk.first_year == 1895


def test_parse_inventory_file_empty():
    assert parse_inventory_file("") == []


# ---------------------------------------------------------------------------
# parse_countries_file
# ---------------------------------------------------------------------------

SAMPLE_COUNTRIES_TXT = textwrap.dedent("""\
AC Antigua and Barbuda
AE United Arab Emirates
US United States
RS Russia
IN India
""")


def test_parse_countries_file():
    result = parse_countries_file(SAMPLE_COUNTRIES_TXT)
    assert result["US"] == "United States"
    assert result["RS"] == "Russia"
    assert result["IN"] == "India"


def test_parse_countries_file_empty():
    assert parse_countries_file("") == {}


# ---------------------------------------------------------------------------
# parse_dly_text — core format parsing
# ---------------------------------------------------------------------------

def test_parse_dly_text_basic():
    """Day 1 of June 1933 TMAX should parse as 36.1°C."""
    line = make_dly_line("USW00023183", 1933, 6, "TMAX", [361])
    obs = parse_dly_text(line)
    assert len(obs) == 1
    assert obs[0].station_id == "USW00023183"
    assert obs[0].obs_date == date(1933, 6, 1)
    assert obs[0].element == "TMAX"
    assert obs[0].value_c == pytest.approx(36.1, abs=0.01)


def test_parse_dly_text_all_days():
    """31 days in July should all parse."""
    day_values = [400 + i * 2 for i in range(31)]
    line = make_dly_line("USW00023183", 2023, 7, "TMAX", day_values)
    obs = parse_dly_text(line)
    assert len(obs) == 31
    assert obs[-1].obs_date == date(2023, 7, 31)


def test_parse_dly_text_missing_values_excluded():
    """Days with -9999 must not appear in output."""
    # Values: days 1, 3, 5 present; 2, 4, 6 missing
    day_values = [361 if i % 2 == 0 else None for i in range(6)]
    line = make_dly_line("USW00023183", 2023, 6, "TMAX", day_values)
    obs = parse_dly_text(line)
    assert len(obs) == 3
    assert all(o.obs_date.day in {1, 3, 5} for o in obs)


def test_parse_dly_text_quality_flagged_excluded():
    """Observations with a non-space QFLAG must be excluded."""
    header = "USW000231832023 6TMAX"[:21]
    # Pad header to 21 chars
    header = f"{'USW00023183':11s}{2023:04d}{6:02d}{'TMAX':4s}"
    # Craft day 1 with QFLAG = 'G' (suspect): value(5) + mflag(1) + qflag='G' + sflag(1)
    day1_flagged = f"{361:5d} G6"   # qflag='G' → should be excluded
    day2_good    = f"{372:5d}  6"   # qflag=' ' → should be included
    # Pad remaining 29 days as missing
    rest = "-9999   " * 29
    line = header + day1_flagged + day2_good + rest
    assert len(line) == 269
    obs = parse_dly_text(line)
    assert len(obs) == 1
    assert obs[0].value_c == pytest.approx(37.2, abs=0.01)


def test_parse_dly_text_element_filter():
    """Default filter only yields TMAX and TMIN."""
    tmax_line = make_dly_line("USW00023183", 2023, 6, "TMAX", [361])
    prcp_line = make_dly_line("USW00023183", 2023, 6, "PRCP", [25])  # precipitation
    obs = parse_dly_text(tmax_line + "\n" + prcp_line)
    assert len(obs) == 1
    assert obs[0].element == "TMAX"


def test_parse_dly_text_no_element_filter():
    """With elements=None, all elements are returned."""
    tmax_line = make_dly_line("USW00023183", 2023, 6, "TMAX", [361])
    prcp_line = make_dly_line("USW00023183", 2023, 6, "PRCP", [25])
    obs = parse_dly_text(tmax_line + "\n" + prcp_line, elements=None)
    assert len(obs) == 2


def test_parse_dly_text_tmin():
    """TMIN values in tenths of °C, including negatives."""
    line = make_dly_line("RSM00024266", 1933, 1, "TMIN", [-678, -650, -700])
    obs = parse_dly_text(line)
    assert len(obs) == 3
    assert obs[0].value_c == pytest.approx(-67.8, abs=0.01)
    assert obs[2].value_c == pytest.approx(-70.0, abs=0.01)


def test_parse_dly_text_feb_30_skipped():
    """Feb 30 cannot be constructed as a valid date — must be skipped."""
    # Make 31-day record for February (some days impossible)
    day_values = [361] * 31
    line = make_dly_line("USW00023183", 2023, 2, "TMAX", day_values)
    obs = parse_dly_text(line)
    # Feb 2023 has 28 days; days 29-31 are not valid dates
    assert all(o.obs_date <= date(2023, 2, 28) for o in obs)
    assert len(obs) == 28


def test_parse_dly_text_empty_string():
    obs = parse_dly_text("")
    assert obs == []


def test_parse_dly_text_short_line_skipped():
    obs = parse_dly_text("TOOSHORT")
    assert obs == []


# ---------------------------------------------------------------------------
# Fixture file integration test
# ---------------------------------------------------------------------------

def test_fixture_file_parses_correctly():
    """The vendored fixture file produces the expected observations."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    # 8 lines, each with multiple valid days
    assert len(obs) > 0
    station_ids = {o.station_id for o in obs}
    assert station_ids == {"USW00023183"}


def test_fixture_contains_engineered_record():
    """Engineered all-time TMAX of 52.2°C on 2023-07-16."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    record = next(
        (o for o in obs if o.obs_date == date(2023, 7, 16) and o.element == "TMAX"),
        None,
    )
    assert record is not None, "Missing 2023-07-16 TMAX observation"
    assert record.value_c == pytest.approx(52.2, abs=0.01)


# ---------------------------------------------------------------------------
# superghcnd_diff parser
# ---------------------------------------------------------------------------

def test_parse_superghcnd_diff_text_same_as_dly():
    """Fixed-width text fallback remains available for small local fixtures."""
    line = make_dly_line("USW00023183", 2024, 6, "TMAX", [440])
    obs_dly = parse_dly_text(line)
    obs_diff = parse_superghcnd_diff_text(line)
    assert len(obs_diff) == 1
    assert obs_diff[0].value_c == obs_dly[0].value_c


def _make_diff_tar(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_parse_superghcnd_diff_tar_csv_insert_update_only():
    """Live NOAA superghcnd_diff files are tar.gz archives of CSV members."""
    payload = _make_diff_tar({
        "insert.csv": "USW00023183,20260715,TMAX,00440,,,0700\n",
        "update.csv": "USW00023183,20260715,TMIN,00250,,,0700\n",
        "delete.csv": "USW00023183,20260714,TMAX,00400,,,0700\n",
    })
    obs = parse_superghcnd_diff_bytes(payload)
    assert [(o.element, o.obs_date, o.value_c) for o in obs] == [
        ("TMAX", date(2026, 7, 15), 44.0),
        ("TMIN", date(2026, 7, 15), 25.0),
    ]


def test_parse_superghcnd_diff_records_include_delete_actions():
    payload = _make_diff_tar({
        "delete.csv": "USW00023183,20260714,TMAX,00400,,,0700\n",
    })
    records = parse_superghcnd_diff_records_bytes(payload)
    assert len(records) == 1
    assert records[0].action == "delete"
    assert records[0].to_daily_obs() is None


def test_parse_superghcnd_diff_rejects_malformed_csv():
    payload = _make_diff_tar({"insert.csv": "USW00023183,20260715,TMAX\n"})
    with pytest.raises(ValueError):
        parse_superghcnd_diff_bytes(payload)


# ---------------------------------------------------------------------------
# compute_thresholds
# ---------------------------------------------------------------------------

def test_compute_thresholds_all_time_max():
    """All-time TMAX is the highest reading across all obs."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    t = compute_thresholds(obs)
    assert t is not None
    assert t.all_time_max_c == pytest.approx(52.2, abs=0.01)
    assert t.all_time_max_year == 2023


def test_compute_thresholds_all_time_min():
    """All-time TMIN is the coldest minimum reading."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    t = compute_thresholds(obs)
    assert t is not None
    assert t.all_time_min_c is not None
    assert t.all_time_min_c < 20.0  # Phoenix nights well below 20°C in this fixture


def test_compute_thresholds_monthly_max():
    """Monthly max for July should be the engineered 52.2°C."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    t = compute_thresholds(obs)
    assert t is not None
    july_max_c, july_max_year = t.monthly_max[7]
    assert july_max_c == pytest.approx(52.2, abs=0.01)
    assert july_max_year == 2023


def test_compute_thresholds_calendar_date_max():
    """Calendar-date max for July 16 is the engineered 52.2°C."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    t = compute_thresholds(obs)
    assert t is not None
    v, y = t.calendar_date_max[(7, 16)]
    assert v == pytest.approx(52.2, abs=0.01)
    assert y == 2023


def test_compute_thresholds_archive_years():
    """Archive span for our fixture is 1933 to 2023 = 91 years."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    t = compute_thresholds(obs)
    assert t is not None
    assert t.archive_years == 91


def test_compute_thresholds_climatological_mean():
    """Climatological mean TMAX for June should be a reasonable Phoenix summer temp."""
    text = (FIXTURES / "USW00023183_excerpt.dly").read_text()
    obs = parse_dly_text(text)
    t = compute_thresholds(obs)
    assert t is not None
    june_mean = t.climatological_mean.get(6)
    assert june_mean is not None
    assert 36.0 < june_mean < 50.0  # Phoenix June is hot but not absurd


def test_compute_thresholds_empty():
    """No obs → returns None."""
    assert compute_thresholds([]) is None


def test_compute_thresholds_tmax_only():
    """With only TMAX obs, TMIN fields remain None."""
    line = make_dly_line("TESTST00000", 2023, 6, "TMAX", [400, 410])
    obs = parse_dly_text(line)
    t = compute_thresholds(obs)
    assert t is not None
    assert t.all_time_max_c == pytest.approx(41.0, abs=0.01)
    assert t.all_time_min_c is None


# ---------------------------------------------------------------------------
# update_thresholds_with_obs
# ---------------------------------------------------------------------------

def test_update_thresholds_new_all_time_max():
    """A new reading that exceeds the current all-time max updates it."""
    base_obs = [DailyObs("ST0000", date(2022, 7, 15), "TMAX", 40.0)]
    t = compute_thresholds(base_obs)
    assert t is not None

    new_obs = [DailyObs("ST0000", date(2023, 7, 16), "TMAX", 42.0)]
    changed = update_thresholds_with_obs(t, new_obs)

    assert changed is True
    assert t.all_time_max_c == pytest.approx(42.0, abs=0.01)
    assert t.all_time_max_year == 2023


def test_update_thresholds_no_change_below_record():
    """A reading on the same calendar-date below the existing record should not update."""
    base_obs = [DailyObs("ST0000", date(2022, 7, 15), "TMAX", 40.0)]
    t = compute_thresholds(base_obs)
    assert t is not None

    # Same month+day (July 15), lower value — no threshold should move
    new_obs = [DailyObs("ST0000", date(2023, 7, 15), "TMAX", 39.0)]
    changed = update_thresholds_with_obs(t, new_obs)

    assert changed is False
    assert t.all_time_max_c == pytest.approx(40.0, abs=0.01)


def test_update_thresholds_new_cold_record():
    """A new TMIN lower than the existing all-time min updates it."""
    base_obs = [DailyObs("POLAR0000", date(2022, 1, 15), "TMIN", -60.0)]
    t = compute_thresholds(base_obs)
    assert t is not None

    new_obs = [DailyObs("POLAR0000", date(2023, 1, 10), "TMIN", -67.8)]
    changed = update_thresholds_with_obs(t, new_obs)

    assert changed is True
    assert t.all_time_min_c == pytest.approx(-67.8, abs=0.01)
    assert t.all_time_min_year == 2023


def test_update_thresholds_new_monthly_max():
    """A new monthly max for a given month updates the monthly record."""
    base_obs = [DailyObs("ST0000", date(2022, 8, 5), "TMAX", 38.0)]
    t = compute_thresholds(base_obs)
    assert t is not None

    new_obs = [DailyObs("ST0000", date(2023, 8, 12), "TMAX", 40.5)]
    changed = update_thresholds_with_obs(t, new_obs)

    assert changed is True
    aug_max, aug_year = t.monthly_max[8]
    assert aug_max == pytest.approx(40.5, abs=0.01)
    assert aug_year == 2023


def test_update_thresholds_empty_new_obs():
    """Passing an empty list of new obs returns False and doesn't change thresholds."""
    base_obs = [DailyObs("ST0000", date(2022, 7, 15), "TMAX", 40.0)]
    t = compute_thresholds(base_obs)
    assert t is not None

    changed = update_thresholds_with_obs(t, [])
    assert changed is False
    assert t.all_time_max_c == pytest.approx(40.0, abs=0.01)


# ---------------------------------------------------------------------------
# StationMeta helper method (country code inferred from ID prefix)
# ---------------------------------------------------------------------------

def test_station_meta_country_code_inferred():
    """Country code is the first 2 chars of station_id."""
    meta = StationMeta(
        station_id="USW00023183",
        lat=33.43, lon=-112.01, elevation_m=337.1,
        state="AZ", name="PHOENIX", gsn_flag="GSN",
        hcn_crn_flag="HCN", wmo_id="72278",
    )
    # The 2-char country prefix from GHCN IDs: US, RS, IN, CA, etc.
    # country_code_inferred() returns the first 2 chars of station_id
    assert meta.country_code_inferred() == "US"
