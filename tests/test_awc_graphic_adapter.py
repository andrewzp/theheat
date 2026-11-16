"""Invented airport bytes only; never live AWC or platform access."""
from copy import deepcopy

import pytest

from src.data import awc_observed
from src.editorial.revisions import fingerprint
from src.media import awc_graphic_adapter as adapter
from tests.test_awc_observed import NOW, install


@pytest.fixture
def bundle(monkeypatch):
    install(monkeypatch)
    finding = awc_observed.nominate(now=NOW)
    return awc_observed.build_bundle(finding, now=NOW).to_dict()


def test_exact_retained_pair_has_own_observed_spec_and_common_linear_axis(bundle):
    spec = adapter.awc_graphic_spec(bundle, expected_bundle_sha256=fingerprint(bundle))
    evidence = spec["evidence"]
    assert spec["template"] == "awc_airport_temperature_pair"
    assert evidence["evidence_type"] == "observed"
    assert evidence["points"] == bundle["raw_signal_dump"]["evidence"]["points"]
    assert evidence["difference_c"] == 65
    assert evidence["axis"] == {"min_c": -20, "max_c": 60, "ticks_c": [-20, 0, 20, 40, 60]}
    assert spec["expected_evidence_sha256"] == fingerprint(evidence)
    assert adapter.source_context(evidence)["points"][0]["station_id"] == "TAAA"
    assert "−20°C" in adapter.delivery_text(evidence)
    assert "45°C" in adapter.delivery_text(evidence)
    assert "2026-11-15 12:00:00 UTC" in adapter.delivery_text(evidence)
    assert "not forecasts or daily extrema" in adapter.full_description(evidence)
    assert "not a national value, record or global ranking" in adapter.delivery_text(evidence)


@pytest.mark.parametrize("field", ["temperature_c", "country", "valid_time", "raw_report_sha256"])
def test_changed_retained_point_cannot_reuse_original_binding(bundle, field):
    expected = fingerprint(bundle)
    changed = deepcopy(bundle)
    changed["raw_signal_dump"]["evidence"]["points"][0][field] = "changed"
    with pytest.raises(adapter.AWCGraphicRefused, match="bundle changed"):
        adapter.awc_graphic_spec(changed, expected_bundle_sha256=expected)
    with pytest.raises(adapter.AWCGraphicRefused, match="not qualified"):
        adapter.awc_graphic_spec(changed, expected_bundle_sha256=fingerprint(changed))


def test_reconstruction_retains_capture_time_and_is_deterministic_without_fetch(bundle, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("a graphic may not hydrate source evidence")
    monkeypatch.setattr(awc_observed, "_read", forbidden)
    a = adapter.awc_graphic_spec(bundle, expected_bundle_sha256=fingerprint(bundle))
    b = adapter.awc_graphic_spec(bundle, expected_bundle_sha256=fingerprint(bundle))
    assert a == b
    assert a["evidence"]["retrieved_at"] == bundle["raw_signal_dump"]["evidence"]["retrieved_at"]
    assert len(adapter.delivery_text(a["evidence"]).encode()) <= 1000


def test_native_image_is_repeatable_and_source_expiry_is_independent(bundle):
    from datetime import timedelta
    from src.media import gist_media
    a = gist_media.prepare_media(bundle)
    b = gist_media.prepare_media(bundle)
    assert a == b
    assert a["kind"] == "gist_awc_observed_pair_v1"
    assert a["png"].startswith(b"\x89PNG\r\n\x1a\n")
    assert len(a["png"]) <= 750000
    assert gist_media.posting_window(bundle, now=NOW)["status"] == "current"
    old = gist_media.posting_window(bundle, now=NOW + timedelta(hours=3))
    assert old["status"] == "unavailable"
    assert old["code"] == "media_source_stale"
    draft = {"review_context": {"two_bot": {"bundle": bundle}}, "media_attachment": a["descriptor"]}
    assert gist_media.media_for_draft(draft, now=NOW) == (a["png"], a["delivery_text"])
    with pytest.raises(ValueError):
        gist_media.media_for_draft(draft, now=NOW + timedelta(hours=3))


@pytest.mark.parametrize('values,axis', [
    ((-90, -30), (-100, 0)), ((1, 65), (0, 80)),
    ((0, 60), (0, 60)), ((-90, 65), (-100, 80)),
])
def test_qualified_source_signs_extremes_and_zero_keep_readable_linear_geometry(monkeypatch, values, axis):
    from tests.test_awc_observed import reports
    from src.media import gist_media
    rows = reports()
    for row, value in zip(rows, values):
        core = ('M' if value < 0 else '') + f'{abs(value):02d}'
        row[0] = f'{row[1]} 151200Z {core}/M95 Q1010'
        row[5] = str(value)
    install(monkeypatch, rows=rows)
    finding = awc_observed.nominate(now=NOW)
    assert finding is not None
    retained = awc_observed.build_bundle(finding, now=NOW).to_dict()
    spec = adapter.awc_graphic_spec(retained, expected_bundle_sha256=fingerprint(retained))
    scale = spec['evidence']['axis']
    assert (scale['min_c'], scale['max_c']) == axis
    assert scale['min_c'] <= 0 <= scale['max_c']
    assert all(scale['min_c'] <= x <= scale['max_c'] for x in values)
    prepared = gist_media.prepare_media(retained)
    assert prepared['png'].startswith(b'\x89PNG\r\n\x1a\n') and len(prepared['png']) <= 750000
    for value in values:
        assert adapter.number(value) + '°C' in prepared['delivery_text']


@pytest.mark.parametrize('path,value', [
    (('capture_sha256', 'catalog'), 'broken'),
    (('difference_c',), 66),
    (('points', 1, 'country_code'), 'NO'),
    (('points', 1, 'station_id'), 'TAAA'),
    (('points', 1, 'maintenance'), True),
    (('points', 1, 'valid_time'), '2026-11-15T11:00:00Z'),
    (('points', 1, 'temperature_c'), float('inf')),
])
def test_malformed_or_changed_source_proof_is_never_a_render_fallback(bundle, path, value):
    changed = deepcopy(bundle)
    node = changed['raw_signal_dump']['evidence']
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    # A valid original bundle identity can never be reused for any changed receipt.
    with pytest.raises(ValueError):
        adapter.awc_graphic_spec(changed, expected_bundle_sha256=fingerprint(bundle))
    # Non-finite values have no canonical identity. The remaining inconsistent
    # proofs also refuse when the caller recomputes the outer bundle hash.
    if value != float('inf'):
        with pytest.raises(ValueError):
            adapter.awc_graphic_spec(changed, expected_bundle_sha256=fingerprint(changed))


def test_qualified_long_unbreakable_airport_holds_instead_of_shrinking_or_clipping(monkeypatch):
    from tests.test_awc_observed import catalog
    from src.media import gist_media
    stations = catalog()
    stations[0]['site'] = 'A' * 85 + ' Airport'
    install(monkeypatch, stations=stations)
    retained = awc_observed.build_bundle(awc_observed.nominate(now=NOW), now=NOW).to_dict()
    adapter.awc_graphic_spec(retained, expected_bundle_sha256=fingerprint(retained))
    with pytest.raises(ValueError) as held:
        gist_media.prepare_media(retained)
    assert held.value.code == 'media_label_overflow'


def test_well_formed_changed_capture_is_a_new_recipe_not_proof_of_authenticity(bundle):
    from src.media import gist_media
    changed = deepcopy(bundle)
    changed['raw_signal_dump']['evidence']['capture_sha256']['observations'] = 'f' * 64
    with pytest.raises(adapter.AWCGraphicRefused, match='bundle changed'):
        adapter.awc_graphic_spec(changed, expected_bundle_sha256=fingerprint(bundle))
    original = gist_media.prepare_media(bundle)
    rebuilt = gist_media.prepare_media(changed)
    assert rebuilt['descriptor'] != original['descriptor']
    # The static projection has no original wire bytes to authenticate a new,
    # well-formed capture hash. Exact recipe identities and independent live
    # source checks, rather than rendering success, govern posting authority.
    assert rebuilt['png'] == original['png']
