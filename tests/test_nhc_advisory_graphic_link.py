"""Invented TCP products: inert official map links never alter claim bytes."""
import pytest

from src.editorial.nhc_advisory import AdvisoryHold, digest, validate_capture
from src.two_bot.intern.nhc_advisory import RetainedAdvisory, build_nhc_advisory_bundle
from tests import nhc_advisory_helpers as h

LINK = ("<a href='https://www.hurricanes.gov/graphics_ep5.shtml?rainqpf.'>"
        "hurricanes.gov/graphics_ep5.shtml?rainqpf.</a>")
NOTE = ("For a complete depiction of forecast rainfall associated with Inventa,\n"
        "please see the National Weather Service Storm Total Rainfall Graphic\n"
        "available at " + LINK + "\n")


def with_note(note=NOTE):
    return h.bulletin().replace("\nSURF:", "\n" + note + "\nSURF:")


@pytest.mark.parametrize("quote", ["'", '"'])
def test_official_reference_link_keeps_exact_source_and_claim_spans(quote):
    link = LINK.replace("'", quote)
    raw = with_note(NOTE.replace(LINK, link)).encode()
    page = h.page(raw.decode())
    value = validate_capture(h.capture(page_bytes=page), h.selected(), now=h.NOW)
    original_slice = raw + b'  '  # h.page deliberately indents its closing pre tag.
    assert value.bulletin.raw == original_slice
    assert page[value.span[0]:value.span[1]] == original_slice
    assert value.bulletin.text(value.hazard) == h.HAZARD
    bundle = build_nhc_advisory_bundle(value)
    record = bundle.raw_signal_dump['nhc_advisory']
    assert record['bulletin_sha256'] == digest(original_slice)
    assert record['source']['page_sha256'] == digest(page)
    assert record['hazard']['text'] == h.HAZARD
    assert [row['text'] for row in record['context']] == [h.CONTEXT]
    assert RetainedAdvisory(bundle).identity() == value.identity()


@pytest.mark.parametrize("link", [
    LINK.replace('https:', 'http:'),
    LINK.replace('www.hurricanes.gov', 'evil.example'),
    LINK.replace('www.hurricanes.gov', 'www.hurricanes.gov.evil.example'),
    LINK.replace('graphics_ep5', 'graphics_ep4'),
    LINK.replace('graphics_ep5', 'graphics_at5'),
    LINK.replace('rainqpf.', 'rainqpf&x=1'),
    LINK.replace("href=", "onclick='alert(1)' href="),
    LINK.replace('hurricanes.gov/graphics_ep5.shtml?rainqpf.</a>', 'different label</a>'),
    LINK.replace('</a>', '<b>altered</b></a>'),
    LINK.replace('</a>', '&nbsp;</a>'),
    LINK.replace('</a>', ''),
    LINK + '<script>bad()</script>',
])
def test_unknown_or_misleading_link_shapes_are_refused(link):
    with pytest.raises(AdvisoryHold):
        validate_capture(h.capture(page_bytes=h.page(with_note(NOTE.replace(LINK, link)))), h.selected(), now=h.NOW)


@pytest.mark.parametrize('paragraph', [
    'RAINFALL: Example Province could flood.\navailable at ' + LINK,
    'RAINFALL: Example Province could flood. available at ' + LINK,
])
def test_link_cannot_become_a_claim_or_place_anchor(paragraph):
    with pytest.raises(AdvisoryHold):
        validate_capture(h.capture(page_bytes=h.page(h.bulletin(hazard=paragraph))), h.selected(), now=h.NOW)


def test_markup_does_not_hide_a_context_or_product_change():
    page = h.page(with_note().replace(h.CONTEXT, 'Gradual weakening is forecast.\navailable at ' + LINK))
    with pytest.raises(AdvisoryHold):
        validate_capture(h.capture(page_bytes=page), h.selected(), now=h.NOW)


def test_reference_link_is_not_accepted_in_arbitrary_product_text():
    page = h.page(with_note().replace('available at ' + LINK, 'hidden ' + LINK))
    with pytest.raises(AdvisoryHold):
        validate_capture(h.capture(page_bytes=page), h.selected(), now=h.NOW)


def test_summary_meridiem_must_agree_with_the_local_issue_line():
    page = h.page(h.bulletin(summary='200 AM MST...2100 UTC'))
    with pytest.raises(AdvisoryHold) as raised:
        validate_capture(h.capture(page_bytes=page), h.selected(), now=h.NOW)
    assert raised.value.code == 'nhc_advisory_time_contradictory'
