"""Invented saved states for the store-backed Gist families (CRW, published radar, NHC cone).

Bundles and retained inputs are deterministic, so a separate process rebuilding the
same family retains byte-identical inputs with the same identities. No real source.
"""
from copy import deepcopy

import pytest

from src.media import gist_crw_media as crw, gist_published_media as published
from tests import gist_published_helpers as ph
from tests.gist_crw_helpers import varied_inputs

CLOCKS = {"crw": ("2026-06-16T13:00:00Z", "2026-06-20T00:00:00Z"),
          "radar": ph.CLOCKS["radar"], "cone": ph.CLOCKS["cone"]}
TYPES = {"crw": "regional_sst_anomaly", "radar": "severe_weather", "cone": "cyclone_land_threat"}
TEXTS = {"crw": "Invented Caribbean satellite analysis runs about 3°C above its daily climatology.",
         "radar": "Invented catastrophic tornado warning near Oklahoma City; radar context only.",
         "cone": "Invented hurricane forecast cone keeps the islands inside the track area."}


def family_bundle(family):
    if family == "crw":
        return varied_inputs("caribbean")[0]
    if family == "radar":
        patch = pytest.MonkeyPatch()
        try:
            return ph.radar_bundle(patch)
        finally:
            patch.undo()
    if family == "cone":
        return ph.cone_bundle()
    raise ValueError(family)


def retain(family, store):
    """Retain this family's invented input; returns the exact identity to select."""
    if family == "crw":
        return crw.retain_packet(store, varied_inputs("caribbean")[1])
    if family == "radar":
        doc, raw, refs, receipt = ph.radar_inputs()
        return published.retain(store, published.radar.FAMILY, doc, raw, refs, receipt)
    doc, raw, refs, receipt = ph.cone_inputs()
    return published.retain(store, "nhc_track_cone_v1", doc, raw, refs, receipt)


def saved_state(family, *, runtime=None):
    """Two drafts sharing one invented retained source, plus an unrelated field."""
    from src.editorial import revisions

    bundle = family_bundle(family)
    drafts = []
    for suffix in ("", "-secondary"):
        draft = dict(id=f"invented-{family}{suffix}", event_id=bundle["event_id"], type=TYPES[family],
                     text=TEXTS[family], status="pending", created_at=CLOCKS[family][0],
                     review_context=dict(two_bot=dict(bundle=deepcopy(bundle))))
        revisions.initialize_revision(draft)
        draft.update(content_revision=1, decision_revision=0)
        drafts.append(draft)
    return {"drafts": drafts, "publish_ledger": {}, "errors": [], "unrelated": {"preserve": True},
            "run_history": [runtime] if runtime else []}
