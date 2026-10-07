"""Invented source-link inputs without importing another test module's fixtures."""

from src.two_bot.types import StoryBundle

URL = "https://www.nhc.noaa.gov/text/SYNTHETIC.shtml"
TEXT = "Synthetic storm strengthens offshore."


def bundle(values=None, kind="cyclone_tier_crossing"):
    return StoryBundle(signal_kind=kind, event_id="synthetic-link", where="Synthetic offshore storm",
        when="2026-10-01T06:00:00Z", headline_metric={"label": "wind", "value": 90, "unit": "kt"},
        raw_signal_dump={"source_name": "Synthetic cyclone advisory", "source_url": URL}, current_facts=[
        {"label": "public_advisory_url", "value": value}
        for value in ([URL] if values is None else values)
    ])
