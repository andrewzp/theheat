"""INVENTED NHC-shaped advisory inputs: an imaginary storm over imaginary places.

Structure mirrors a public TCP product page (HTML chrome around one <pre>
bulletin) and a CurrentStorms index row. Nothing here is real weather, a real
storm, a retained production page or a positive model-quality fixture.
"""
from datetime import UTC, datetime, timedelta
import json

from src.editorial.nhc_advisory import AdvisoryCapture, nomination

ISSUED = datetime(2026, 10, 29, 21, tzinfo=UTC)
CAPTURED = ISSUED + timedelta(minutes=26)
NOW = CAPTURED + timedelta(minutes=4)
STORM, BIN, NAME = "EP492026", "EP5", "Inventa"
URL = "https://www.nhc.noaa.gov/text/MIATCPEP5.shtml"
HAZARD = ("RAINFALL: Tropical Depression Inventa is expected to produce additional rainfall\n"
          "of 1 to 3 inches across Example Province through tonight. This rainfall could\n"
          "lead to flash flooding and mudslides in areas of steep terrain.")
CONTEXT = "Gradual weakening is forecast during the next day or so."


def bulletin(*, advisory="34", hazard=HAZARD, context=CONTEXT, local="200 PM MST Thu Oct 29 2026",
             summary="200 PM MST...2100 UTC", wmo="WTPZ35 KNHC 292031", extra="", terminator="$$",
             office=f"NWS National Hurricane Center Miami FL       {STORM}", awips="TCPEP5",
             title=None):
    title = title or f"Tropical Depression {NAME} Advisory Number  {advisory}"
    lines = ["000", wmo, awips, " ", "BULLETIN", title, office, local, "",
             f"...INVENTED FIXTURE DEPRESSION {NAME.upper()} NOT A REAL STORM...", "",
             f"SUMMARY OF {summary}...INFORMATION", "----------------------------------------------",
             "LOCATION...20.0N 110.0W", "MAXIMUM SUSTAINED WINDS...30 MPH...45 KM/H", "",
             "WATCHES AND WARNINGS", "--------------------", "There are no coastal watches or warnings in effect.", "",
             "DISCUSSION AND OUTLOOK", "----------------------",
             f"At 200 PM MST, the center of Tropical Depression {NAME} was located near",
             "latitude 20.0 North, longitude 110.0 West." + (" " + context if context else ""), "",
             "HAZARDS AFFECTING LAND", "----------------------", hazard, "",
             "SURF: Invented swells could affect Example Coast during the next day.", "", extra,
             "NEXT ADVISORY", "-------------", "Next complete advisory at 800 PM MST.", "", terminator,
             "Forecaster Fixture"]
    return "\n".join(lines) + "\n"


def page(text=None, *, before="", after=""):
    body = bulletin() if text is None else text
    return ("<!DOCTYPE html>\n<html><head><title></title><script>var nav=1;</script></head><body>\n"
            "<div class=\"nav\"><a href=\"/\">Home</a> <pre-not-a-tag></div>\n" + before +
            "<div class=\"textproduct\">\n  <pre>" + body + "  </pre>\n  </div>" + after +
            "\n<div class=\"footer\">Invented footer</div></body></html>\n").encode()


def index(*, advisory="34", issuance="2026-10-29T21:00:00.000Z", url=URL, name=NAME, storms=None, extra=None):
    row = {"id": STORM.lower(), "binNumber": BIN, "name": name, "classification": "TD",
           "intensity": "25", "pressure": "1006", "lastUpdate": issuance,
           "publicAdvisory": {"advNum": advisory, "issuance": issuance,
                              "fileUpdateTime": "2026-10-29T20:31:41.000Z", "url": url}}
    if extra:
        row.update(extra)
    return json.dumps({"activeStorms": storms if storms is not None else [row]}).encode()


def nominated(**changes):
    value = {"storm_id": STORM, "bin": BIN, "advisory": "34", "hazard": "RAINFALL",
             "place": "Example Province", "country": "ZZ", "freshness_minutes": 30}
    value.update(changes)
    return value


def capture(*, page_bytes=None, index_bytes=None, captured=CAPTURED):
    return AdvisoryCapture(index_bytes if index_bytes is not None else index(),
                           page_bytes if page_bytes is not None else page(),
                           captured.strftime("%Y-%m-%dT%H:%M:%SZ"))


def selected(**changes):
    return nomination(nominated(**changes))
