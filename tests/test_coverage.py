from src.coverage import is_us_location, resolve_continent


def test_us_forms_resolve_to_north_america():
    assert is_us_location("US") and is_us_location("United States")
    assert is_us_location("Northern Mariana Islands [United States]")
    assert resolve_continent("United States") == "North America"
    assert resolve_continent("US") == "North America"


def test_non_us_resolves_via_map():
    assert not is_us_location("United Kingdom")
    assert resolve_continent("France") == "Europe"
    assert resolve_continent("China") == "Asia"


def test_unknown_is_unknown():
    assert resolve_continent("Atlantis") == "Unknown"
    assert resolve_continent("") == "Unknown"
    assert resolve_continent(None) == "Unknown"
