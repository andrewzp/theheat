"""Invented source-link inputs without importing another test module's fixtures."""

from dataclasses import replace

from tests.two_bot.conftest import _bundle

URL = "https://www.nhc.noaa.gov/text/SYNTHETIC.shtml"
TEXT = "Synthetic storm strengthens offshore."


def bundle(values=None, kind="cyclone_tier_crossing"):
    return replace(_bundle(), signal_kind=kind, current_facts=[
        {"label": "public_advisory_url", "value": value}
        for value in ([URL] if values is None else values)
    ])
