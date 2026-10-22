"""Invented GHCN-Daily stations whose dispatch winner is each station comparator.

Entirely synthetic bytes for local tests: one diff day, six station archives and a
read-only threshold baseline. Each station's current reading wins exactly one
TMAX/TMIN x archive/month/calendar-date comparison under the existing cascade.
"""
from datetime import UTC, date, datetime, timedelta
import io
import tarfile

from scripts import threshold_artifacts as artifacts
from src.data import ghcn_db
from src.data.ghcn_format import DailyObs, compute_thresholds
from src.storage import ghcn_runtime_inputs as inputs
from tests.test_ghcn_time_integrity import dly

# Selection field -> station number. Stations are far apart, each in its own
# invented country, so neither clustering nor the per-country individual cap
# removes one. Values are tenths of a degree Celsius.
VARIANTS = {"all_time_high": 0, "monthly_high": 100, "calendar_date_high": 200,
            "all_time_low": 300, "monthly_low": 400, "calendar_date_low": 500}
COUNTRIES = {number: ("X" + "ABCDEF"[index], "Example " + "ABCDEF"[index])
             for index, number in enumerate(VARIANTS.values())}


def station_id(number):
    return f"USW{number:08d}"


def _month_shift(day, months, *, years=1):
    month = (day.month - 1 + months) % 12 + 1
    return date(day.year - years, month, 1)


def _history(day, field):
    """A complete 24-year calendar with one missing and one QC-rejected cell per variable."""
    start = day.replace(year=day.year - 24)  # Multiples of four years keep 29 February valid.
    same_month = date(day.year - 2, day.month, 1 if day.day != 1 else 2)
    same_date = day.replace(year=day.year - 4)
    other_month = _month_shift(day, 6)
    high, low = field.endswith("_high"), field.endswith("_low")
    special = {}
    if field == "all_time_high":
        special[(other_month, "TMAX")] = 350
    elif field == "monthly_high":
        special[(other_month, "TMAX")] = 500
        special[(same_month, "TMAX")] = 350
    elif field == "calendar_date_high":
        special[(same_month, "TMAX")] = 500
        special[(same_date, "TMAX")] = 300
    else:
        # Low stations need a current TMAX above the cached discovery threshold
        # without any TMAX comparator, so the archive holds a higher same-date TMAX.
        special[(same_date, "TMAX")] = 500
    if field == "all_time_low":
        special[(other_month, "TMIN")] = -50
    elif field == "monthly_low":
        special[(other_month, "TMIN")] = -400
        special[(same_month, "TMIN")] = -50
    elif field == "calendar_date_low":
        special[(same_month, "TMIN")] = -400
        special[(same_date, "TMIN")] = 0
    assert high or low
    quiet = {"TMAX": 280, "TMIN": 20 if field == "calendar_date_low" else 100}
    rows = []
    for index in range((day - start).days):
        at = start + timedelta(days=index)
        for element, missing, rejected in (("TMAX", 10, 20), ("TMIN", 30, 40)):
            value = special.get((at, element), quiet[element])
            rows.append((at, element, -9999 if index == missing else value, "S" if index == rejected else "", "T"))
    return rows


CURRENT = {"all_time_high": (455, 100), "monthly_high": (400, 100), "calendar_date_high": (330, 100),
           "all_time_low": (330, -255), "monthly_low": (330, -150), "calendar_date_low": (330, -50)}


def _diff(day, fields):
    text = "".join(f"{station_id(VARIANTS[field])},{day:%Y%m%d},{element},{value},,,T,\n"
                   for field in fields for element, value in zip(("TMAX", "TMIN"), CURRENT[field]))
    raw = text.encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        member = tarfile.TarInfo("superghcnd_insert.csv")
        member.size = len(raw)
        archive.addfile(member, io.BytesIO(raw))
    return stream.getvalue()


def variant_source(folder, fields=tuple(VARIANTS), tracked=()):
    """The source_bytes shape for the requested comparator stations only.

    ``tracked`` stations (an existing draft's claim) get a quiet verified archive
    and no current reading, so they never become a comparator candidate.
    """
    now = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=3)
    day = now.date() - timedelta(days=1)
    database = folder / "invented-variants.sqlite"
    with ghcn_db.open_db(database) as c:
        for number in range(1000):
            sid = station_id(number)
            code, country = COUNTRIES.get(number, ("US", "United States"))
            c.execute("INSERT INTO stations(station_id,name,country_code,country_name,state,lat,lon,is_active,"
                      "tmax_archive_years,archive_years) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (sid, f"INVENTED STATION {number}", code, country, "UT", 40 + number * 0.05, -111., 1, 24, 24))
            ghcn_db.upsert_thresholds(c, compute_thresholds([DailyObs(sid, date(2020, day.month, day.day), "TMAX", 31.9)]))
        c.commit()
    manifest = folder / "invented-variants.version"
    stats = dict(release="thresholds-latest", sha256=artifacts.digest(database)[0], bytes=str(database.stat().st_size),
                 **artifacts.database_stats(database))
    manifest.write_text("".join(f"{k}={v}\n" for k, v in stats.items()))
    baseline = inputs.Baseline(database, manifest, stats["sha256"], artifacts.digest(manifest)[0])
    at = now.isoformat().replace("+00:00", "Z")
    responses = [inputs.InventedResponse("diff", (now.date() - timedelta(days=n)).isoformat(), at,
                                         _diff(day, fields) if n == 1 else _diff(day, ())) for n in range(1, 4)]
    for field in fields:
        sid = station_id(VARIANTS[field])
        current = [(day, element, value, "", "T") for element, value in zip(("TMAX", "TMIN"), CURRENT[field])]
        responses.append(inputs.InventedResponse("station_archive", sid, at, dly(_history(day, field) + current, sid)))
    for sid in tracked:
        quiet = [(day.replace(year=day.year - 24) + timedelta(days=n), element, value, "", "T")
                 for n in range(24 * 365) for element, value in (("TMAX", 280), ("TMIN", 100))]
        responses.append(inputs.InventedResponse("station_archive", sid, at, dly(quiet, sid)))
    return dict(baseline=baseline, responses=responses, day=day, now=at,
                started_at=(now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                completed_at=(now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"))
