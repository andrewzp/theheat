"""Tests for NOAA ENSO/ONI data."""

from datetime import date

import responses

from src.data.enso import ENSOReading, fetch_enso_data, detect_transition

SAMPLE_YEAR = date.today().year
SAMPLE_ONI_TEXT = f"""SEAS    YR   TOTAL   APTS   ANOM
DJF    {SAMPLE_YEAR}    -0.8   26.1   -0.8
JFM    {SAMPLE_YEAR}    -0.6   26.3   -0.6
FMA    {SAMPLE_YEAR}    -0.3   26.8   -0.3
MAM    {SAMPLE_YEAR}     0.1   27.5    0.1
AMJ    {SAMPLE_YEAR}     0.3   28.0    0.3
MJJ    {SAMPLE_YEAR}     0.6   28.5    0.6
"""


class TestFetchEnsoData:
    @responses.activate
    def test_happy_path_parses_readings(self):
        responses.add(
            responses.GET,
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            body=SAMPLE_ONI_TEXT,
            status=200,
        )
        readings = fetch_enso_data()
        assert len(readings) == 6
        assert all(isinstance(r, ENSOReading) for r in readings)

    @responses.activate
    def test_classifies_el_nino(self):
        responses.add(
            responses.GET,
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            body=SAMPLE_ONI_TEXT,
            status=200,
        )
        readings = fetch_enso_data()
        # Last reading has ONI 0.6 >= 0.5 threshold
        assert readings[-1].status == "El Nino"
        assert readings[-1].oni_value == 0.6

    @responses.activate
    def test_classifies_la_nina(self):
        responses.add(
            responses.GET,
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            body=SAMPLE_ONI_TEXT,
            status=200,
        )
        readings = fetch_enso_data()
        # First reading has ONI -0.8 <= -0.5 threshold
        assert readings[0].status == "La Nina"

    @responses.activate
    def test_classifies_neutral(self):
        responses.add(
            responses.GET,
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            body=SAMPLE_ONI_TEXT,
            status=200,
        )
        readings = fetch_enso_data()
        # MAM 2024 has ONI 0.1 (between -0.5 and 0.5)
        mam = [r for r in readings if r.season == "MAM"][0]
        assert mam.status == "Neutral"

    @responses.activate
    def test_api_error_returns_empty(self):
        responses.add(
            responses.GET,
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            status=500,
        )
        assert fetch_enso_data() == []

    @responses.activate
    def test_event_id_format(self):
        responses.add(
            responses.GET,
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            body=SAMPLE_ONI_TEXT,
            status=200,
        )
        readings = fetch_enso_data()
        assert readings[0].event_id == f"enso_DJF_{SAMPLE_YEAR}"


class TestDetectTransition:
    def test_detects_la_nina_to_el_nino(self):
        readings = [
            ENSOReading("DJF", 2024, -0.8, "La Nina", "enso_DJF_2024"),
            ENSOReading("JFM", 2024, -0.6, "La Nina", "enso_JFM_2024"),
            ENSOReading("FMA", 2024, -0.3, "Neutral", "enso_FMA_2024"),
            ENSOReading("MAM", 2024, 0.6, "El Nino", "enso_MAM_2024"),
        ]
        result = detect_transition(readings)
        assert result is not None
        assert result["from_status"] == "Neutral"
        assert result["to_status"] == "El Nino"
        assert result["oni_value"] == 0.6
        assert result["previous_duration_months"] == 2  # La Nina lasted 2 months

    def test_no_transition_same_state(self):
        readings = [
            ENSOReading("DJF", 2024, -0.8, "La Nina", "enso_DJF_2024"),
            ENSOReading("JFM", 2024, -0.6, "La Nina", "enso_JFM_2024"),
        ]
        assert detect_transition(readings) is None

    def test_transition_to_neutral_ignored(self):
        readings = [
            ENSOReading("DJF", 2024, -0.8, "La Nina", "enso_DJF_2024"),
            ENSOReading("JFM", 2024, -0.1, "Neutral", "enso_JFM_2024"),
        ]
        assert detect_transition(readings) is None

    def test_counts_previous_active_duration(self):
        readings = [
            ENSOReading("DJF", 2023, -0.8, "La Nina", "enso_DJF_2023"),
            ENSOReading("JFM", 2023, -0.7, "La Nina", "enso_JFM_2023"),
            ENSOReading("FMA", 2023, -0.6, "La Nina", "enso_FMA_2023"),
            ENSOReading("MAM", 2023, -0.1, "Neutral", "enso_MAM_2023"),
            ENSOReading("AMJ", 2023, 0.6, "El Nino", "enso_AMJ_2023"),
        ]
        result = detect_transition(readings)
        # Counts La Nina duration (3 months), not the Neutral gap
        assert result["previous_duration_months"] == 3

    def test_too_few_readings_returns_none(self):
        assert detect_transition([]) is None
        assert detect_transition([ENSOReading("DJF", 2024, 0.6, "El Nino", "x")]) is None

    def test_event_id_format(self):
        readings = [
            ENSOReading("DJF", 2024, 0.1, "Neutral", "enso_DJF_2024"),
            ENSOReading("JFM", 2024, 0.6, "El Nino", "enso_JFM_2024"),
        ]
        result = detect_transition(readings)
        assert result["event_id"] == "enso_transition_El_Nino_2024"
