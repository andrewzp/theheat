"""Invented METAR protocol cases; no source, provider or platform access."""
from copy import deepcopy
import csv
from datetime import UTC, datetime, timedelta
import gzip
import io
import json

import pytest

from src.data import awc_observed as source

NOW = datetime(2026, 11, 15, 12, 10, tzinfo=UTC)
TARGET = "2026-11-15T12:00:00Z"
HEADER = ["raw_text", "station_id", "observation_time", "latitude", "longitude", "temp_c",
          "metar_type", "maintenance_indicator_on", "no_signal", "sky_cover", "sky_cover"]


def catalog():
    return [{"icaoId": "TAAA", "site": "North Test Arpt", "country": "NO", "lat": 60, "lon": 10,
             "siteType": ["METAR", "TAF"]},
            {"icaoId": "TBBB", "site": "South Test Arpt", "country": "CL", "lat": -30, "lon": -70,
             "siteType": ["METAR"]}]


def reports():
    return [["TAAA 151200Z AUTO 00000KT CAVOK M20/M25 Q1010 NOSIG", "TAAA", TARGET,
             "60", "10", "-20", "METAR", "", "TRUE", "", ""],
            ["TBBB 151200Z 00000KT CAVOK 45/20 Q1010", "TBBB", TARGET,
             "-30", "-70", "45", "METAR", "", "", "", ""]]


def csv_bytes(rows=None, header=None):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(HEADER if header is None else header)
    writer.writerows(reports() if rows is None else rows)
    return out.getvalue().encode()


def metadata(rows=None):
    return source.parse_stations(json.dumps(catalog() if rows is None else rows).encode())


def install(monkeypatch, *, rows=None, stations=None, xml=None):
    calls = []
    catalog_raw = gzip.compress(json.dumps(catalog() if stations is None else stations).encode(), mtime=0)
    reports_raw = gzip.compress(csv_bytes(rows), mtime=0)
    def read(url, *, params=None):
        calls.append((url, params))
        if url == source.STATIONS_URL:
            return catalog_raw
        if url == source.METARS_URL:
            return reports_raw
        if url == source.HISTORY_URL:
            assert params == {"ids": "TAAA,TBBB", "format": "xml", "taf": "false", "hours": 2, "date": TARGET}
            return history_xml() if xml is None else xml
        pytest.fail("unowned URL")
    monkeypatch.setattr(source, "_read", read)
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    monkeypatch.setenv(source.ENABLE_FLAG, "1")
    return calls


def history_xml(rows=None):
    from xml.etree.ElementTree import Element, SubElement, tostring
    root = Element("response")
    rows = reports() if rows is None else rows
    data = SubElement(root, "data", {"num_results": str(len(rows))})
    for values in rows:
        row = dict(zip(HEADER, values))
        metar = SubElement(data, "METAR")
        for key in ("raw_text", "station_id", "observation_time", "latitude", "longitude", "temp_c", "metar_type"):
            SubElement(metar, key).text = row[key]
        flags = SubElement(metar, "quality_control_flags")
        SubElement(flags, "no_signal").text = row["no_signal"]
        if row["maintenance_indicator_on"]:
            SubElement(flags, "maintenance_indicator_on").text = row["maintenance_indicator_on"]
    return tostring(root)


def test_cache_to_compact_pair_to_independent_historical_recheck(monkeypatch):
    calls = install(monkeypatch)
    evidence = source.nominate(now=NOW)
    assert evidence["difference_c"] == 65
    assert evidence["points"][0]["country"] == "Norway"
    assert evidence["points"][1]["country"] == "Chile"
    bundle = source.build_bundle(evidence, now=NOW)
    assert len(json.dumps(bundle.to_dict()).encode()) < 4096
    assert all(word not in json.dumps(bundle.to_dict()) for word in ("NOSIG", "Q1010", "sky_cover"))
    assert source.current_bundle_hold(bundle, live=True, now=NOW) is None
    assert [url for url, _ in calls] == [source.STATIONS_URL, source.METARS_URL, source.HISTORY_URL, source.STATIONS_URL]
    assert bundle.event_id == "metar_pair_TAAA_TBBB_2026-11-15"


@pytest.mark.parametrize("change", ["same", "different", "malformed"])
def test_duplicate_observation_identity_is_held_in_every_order(change):
    rows = reports()
    extra = deepcopy(rows[0])
    if change == "different":
        extra[5] = "-30"
    elif change == "malformed":
        extra[2] = "not a time"
    rows.append(extra)
    for supplied in (rows, list(reversed(rows))):
        assert set(source.parse_metars(csv_bytes(supplied), metadata(), now=NOW)) == {"TBBB"}


@pytest.mark.parametrize("change", ["same", "country", "name", "malformed"])
def test_duplicate_catalog_identity_is_held_in_every_order(change):
    rows = catalog()
    extra = deepcopy(rows[0])
    if change == "country":
        extra["country"] = "GB"
    elif change == "name":
        extra["site"] = "Other Test Arpt"
    elif change == "malformed":
        extra["lat"] = "NaN"
    rows.append(extra)
    for supplied in (rows, list(reversed(rows))):
        assert set(metadata(supplied)) == {"TBBB"}


@pytest.mark.parametrize("key,value", [
    ("temp_c", "NaN"), ("temp_c", ""), ("temp_c", "-91"), ("temp_c", "66"),
    ("temp_c", "-30"), ("observation_time", "2026-11-15T12:11:00Z"),
    ("observation_time", "2026-11-15T10:00:00Z"), ("observation_time", "2026-11-15T12:00:00"),
    ("maintenance_indicator_on", "TRUE"), ("maintenance_indicator_on", "unknown"),
    ("metar_type", "TAF"), ("latitude", "61"), ("longitude", "NaN"),
    ("raw_text", "TBBB 151200Z M20/M25"), ("raw_text", "TAAA 151100Z M20/M25"),
    ("raw_text", "TAAA 151200Z NOSIG M20/M25"),
])
def test_invalid_point_cannot_supply_the_pair(key, value):
    rows = reports()
    rows[0][HEADER.index(key)] = value
    assert set(source.parse_metars(csv_bytes(rows), metadata(), now=NOW)) == {"TBBB"}


def test_no_signal_is_nosig_not_an_observation_failure_and_trend_is_not_temperature():
    rows = reports()
    rows[0][0] += " TEMPO 30/20"
    points = source.parse_metars(csv_bytes(rows), metadata(), now=NOW)
    assert points["TAAA"]["temperature_c"] == -20


@pytest.mark.parametrize("extra", ["T12010250", "T10200250 T10200250"])
def test_precise_temperature_disagreement_or_ambiguity_is_held(extra):
    rows = reports()
    rows[0][0] = "TAAA 151200Z M20/M25 RMK " + extra
    assert "TAAA" not in source.parse_metars(csv_bytes(rows), metadata(), now=NOW)


@pytest.mark.parametrize("change", ["core-column", "missing-column", "row-width", "gzip-truncated", "gzip-extra"])
def test_malformed_container_is_refused(change):
    rows, header = reports(), list(HEADER)
    if change == "core-column":
        header[-1] = "temp_c"
    elif change == "missing-column":
        header[5] = "other"
    elif change == "row-width":
        rows[0].pop()
    if change.startswith("gzip"):
        raw = gzip.compress(csv_bytes())
        raw = raw[:-4] if change == "gzip-truncated" else raw + gzip.compress(b"extra")
        with pytest.raises(source.ObservedHeld):
            source._unzip(raw)
    else:
        with pytest.raises(source.ObservedHeld):
            source.parse_metars(csv_bytes(rows, header), metadata(), now=NOW)


@pytest.mark.parametrize("change", ["same-country", "below-floor", "mountain", "platform", "no-metadata"])
def test_no_nominated_story_without_the_explicit_airport_comparison(monkeypatch, change):
    rows, stations = reports(), catalog()
    if change == "same-country":
        stations[1]["country"] = "NO"
    elif change == "below-floor":
        rows[1][0] = rows[1][0].replace("45/20", "35/20")
        rows[1][5] = "35"
    elif change in ("mountain", "platform"):
        stations[0]["site"] = "North Test Mountain" if change == "mountain" else "North Test Platform"
    else:
        stations.pop(0)
    install(monkeypatch, rows=rows, stations=stations)
    assert source.nominate(now=NOW) is None


@pytest.mark.parametrize("change", ["value", "missing", "duplicate", "unrequested", "taf", "entity", "declared-count"])
def test_independent_history_disagreement_holds_the_source(monkeypatch, change):
    install(monkeypatch)
    bundle = source.build_bundle(source.nominate(now=NOW), now=NOW)
    rows = reports()
    if change == "value":
        rows[0][0] = rows[0][0].replace("M20/M25", "M21/M25")
        rows[0][5] = "-21"
    elif change == "missing":
        rows.pop(0)
    elif change == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif change == "unrequested":
        rows[0][1] = "TCCC"
    elif change == "taf":
        rows[0][6] = "TAF"
    xml = history_xml(rows)
    if change == "entity":
        xml = b'<!DOCTYPE response [<!ENTITY x "unsafe">]>' + xml
    elif change == "declared-count":
        xml = xml.replace(b'num_results="2"', b'num_results="3"')
    install(monkeypatch, xml=xml)
    assert source.current_bundle_hold(bundle, live=True, now=NOW)


def test_later_observation_does_not_replace_or_invalidate_retained_exact_target(monkeypatch):
    install(monkeypatch)
    bundle = source.build_bundle(source.nominate(now=NOW), now=NOW)
    rows = reports()
    newer = deepcopy(rows[0])
    newer[2] = "2026-11-15T12:05:00Z"
    newer[0] = newer[0].replace("151200Z", "151205Z")
    install(monkeypatch, xml=history_xml([newer, *rows]))
    assert source.current_bundle_hold(bundle, live=True, now=NOW) is None


@pytest.mark.parametrize("change", ["kind", "event", "schema", "citation", "value", "extra-point-field", "date"])
def test_retained_proof_cannot_be_relabelled_or_changed(monkeypatch, change):
    calls = install(monkeypatch)
    bundle = source.build_bundle(source.nominate(now=NOW), now=NOW).to_dict()
    evidence = bundle["raw_signal_dump"]["evidence"]
    if change == "kind":
        bundle["signal_kind"] = "all_time_high"
    elif change == "event":
        bundle["event_id"] = "other"
    elif change == "schema":
        evidence["schema"] = "other"
    elif change == "citation":
        evidence["source_url"] = "https://example.invalid"
    elif change == "value":
        evidence["points"][0]["temperature_c"] = -30
    elif change == "extra-point-field":
        evidence["points"][0]["new_instruction"] = "publish me"
    else:
        evidence["points"][0]["valid_time"] = "2026-11-15T11:00:00Z"
    assert source.current_bundle_hold(bundle, live=True, now=NOW)
    assert len(calls) == 2  # no live recheck of corrupt evidence


def test_time_window_cannot_expire_during_a_source_read(monkeypatch):
    install(monkeypatch)
    bundle = source.build_bundle(source.nominate(now=NOW), now=NOW)
    clocks = iter([NOW, NOW, NOW, NOW + timedelta(hours=2)])
    assert source.current_bundle_hold(bundle, live=True, now=lambda: next(clocks)) == "awc_observation_expired"


def test_static_bindings_grant_no_source_truth(monkeypatch):
    install(monkeypatch)
    evidence = source.nominate(now=NOW)
    evidence["points"][0]["temperature_c"] = -21
    evidence["difference_c"] = 66
    bundle = source.build_bundle(evidence, now=NOW)
    assert source.current_bundle_hold(bundle, now=NOW) is None
    assert source.current_bundle_hold(bundle, live=True, now=NOW) == "awc_source_changed"


def test_duplicate_json_fields_never_choose_a_country_or_identity():
    raw = json.dumps(catalog()).replace('"country": "NO"', '"country": "NO", "country": "CL"').encode()
    with pytest.raises(source.ObservedHeld):
        source.parse_stations(raw)


@pytest.mark.parametrize("alteration", ["wrong-sign", "missing-value", "forecast", "record", "missing-date", "missing-airport"])
def test_copy_cannot_upgrade_or_omit_the_observation_scope(monkeypatch, alteration):
    install(monkeypatch)
    bundle = source.build_bundle(source.nominate(now=NOW), now=NOW)
    text = "At 12:00 UTC Nov 15, North Test airport, Norway, recorded −20°C; South Test airport, Chile, 45°C—a 65°C gap."
    assert source.claim_failures(text, bundle, now=NOW) == []
    if alteration == "wrong-sign":
        text = text.replace("−20°C", "20°C")
    elif alteration == "missing-value":
        text = text.replace("65°C", "large")
    elif alteration == "forecast":
        text = text.replace("recorded", "is forecast to reach")
    elif alteration == "record":
        text = text.replace("gap", "record")
    elif alteration == "missing-date":
        text = text.replace("Nov 15", "today")
    else:
        text = text.replace("airport", "town")
    assert source.claim_failures(text, bundle, now=NOW)
