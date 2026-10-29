"""Attributed NHC forecast facts from one validated public advisory; never a fetch.

The bundle carries the exact bulletin slice (byte offsets into the retained HTTP
response), the selected index values, hashes of both original responses and the
explicit nomination. It carries no expiry fact: NHC public advisories state none,
so the upstream expiry stays explicitly unknown, and the operator recheck deadline
is recorded with its own label. A retained bundle is revalidated by rebuilding it
from its own record and comparing exact captures.
"""
from __future__ import annotations

from datetime import timedelta
import json
from typing import Any

from src.editorial.nhc_advisory import (
    INDEX_URL, ISSUER, OPERATOR_RULE, ORIGIN, SCHEMA, SOURCE_NAME, UPSTREAM_EXPIRY_STATUS, AdvisoryEvidence,
    AdvisoryHold, AdvisoryNomination, Bulletin, advisory_key, check_times, digest, iso, nomination, parse_bulletin, place_span,
    utc,
)
from src.two_bot.bundle_capture import BundleCaptureError, capture_bundle
from src.two_bot.types import StoryBundle

SIGNAL_KIND = "nhc_advisory"
_SOURCE_KEYS = frozenset({"index_url", "advisory_url", "index_sha256", "index_bytes", "page_sha256", "page_bytes",
                          "bulletin_start", "bulletin_end", "original_language"})
_ROW_KEYS = frozenset({"id", "binNumber", "name", "advNum", "issuance", "url"})


def _event_id(selected: AdvisoryNomination) -> str:
    return (f"nhc_advisory:{selected.storm_id.lower()}:{selected.advisory.lower()}:"
            f"{selected.hazard.lower().replace(' ', '_')}")


def _record(evidence: AdvisoryEvidence) -> dict:
    selected, bulletin, capture = evidence.nomination, evidence.bulletin, evidence.capture
    deadline = evidence.deadline
    return {
        "schema": SCHEMA,
        "assertion_kind": "attributed_forecast_not_observation",
        "nomination": selected.as_dict(),
        "source": {"index_url": INDEX_URL, "advisory_url": selected.advisory_url,
                   "index_sha256": digest(capture.index_bytes), "index_bytes": len(capture.index_bytes),
                   "page_sha256": digest(capture.page_bytes), "page_bytes": len(capture.page_bytes),
                   "bulletin_start": evidence.span[0], "bulletin_end": evidence.span[1],
                   "original_language": "en_by_fixed_product_identity"},
        "index_row": {k: evidence.row[k] for k in ("id", "binNumber", "name", "advNum", "issuance", "url")},
        "bulletin_utf8": bulletin.raw.decode("ascii"),
        "bulletin_sha256": digest(bulletin.raw),
        "product": {"wmo_header": bulletin.wmo_header, "awips_id": bulletin.awips_id, "title": bulletin.title,
                    "storm_kind": bulletin.storm_kind, "storm_name": bulletin.storm_name,
                    "advisory": bulletin.advisory, "atcf_id": bulletin.atcf_id},
        "times": {"issued_at": bulletin.issued_at, "captured_at": capture.captured_at,
                  "upstream_expiry": None, "upstream_expiry_status": UPSTREAM_EXPIRY_STATUS,
                  "operator_recheck_deadline": iso(deadline), "operator_recheck_rule": OPERATOR_RULE},
        "hazard": {"key": selected.hazard, "start": evidence.hazard[0], "end": evidence.hazard[1],
                   "text": bulletin.text(evidence.hazard)},
        "place": {"name": selected.place, "start": evidence.place[0], "end": evidence.place[1]},
        "context": [{"start": s, "end": e, "text": bulletin.text((s, e))} for s, e in bulletin.context],
    }


def _bundle(record: dict, bulletin: Bulletin, selected: AdvisoryNomination) -> StoryBundle:
    url = selected.advisory_url
    provenance = {"source_name": SOURCE_NAME, "source_url": url, "issued_at": bulletin.issued_at,
                  "content_sha256": record["bulletin_sha256"]}
    hazard_text = record["hazard"]["text"]
    facts: list[dict[str, Any]] = [dict(label=label, value=value, **provenance) for label, value in (
        ("issuing_authority", f"{ISSUER} ({SOURCE_NAME})"),
        ("storm", f"{bulletin.storm_kind} {bulletin.storm_name}"),
        ("advisory_number", bulletin.advisory),
        ("issued_at", bulletin.issued_at),
        ("forecast_hazard_statement", hazard_text),
        ("forecast_place", selected.place),
    )]
    facts += [dict(label="source_reported_context", value=row["text"], **provenance) for row in record["context"]]
    return StoryBundle(signal_kind=SIGNAL_KIND, where=selected.place, when=bulletin.issued_at,
                       event_id=_event_id(selected),
                       headline_metric={"label": "nhc_forecast_hazard", "value": hazard_text},
                       current_facts=facts, country=selected.country,
                       raw_signal_dump={"source_name": SOURCE_NAME, "source_url": url, "nhc_advisory": record})


def build_nhc_advisory_bundle(evidence: AdvisoryEvidence) -> StoryBundle:
    """Writer facts from already validated evidence; the bound holds, never truncates."""
    if type(evidence) is not AdvisoryEvidence:
        raise AdvisoryHold("nhc_advisory_capture_invalid")
    bundle = _bundle(_record(evidence), evidence.bulletin, evidence.nomination)
    try:
        capture_bundle(bundle)
    except BundleCaptureError as exc:
        raise AdvisoryHold("nhc_advisory_bundle_bound" if str(exc) == "bundle_capture_too_large"
                           else "nhc_advisory_bundle_invalid") from None
    return bundle


def is_nhc_advisory(bundle: Any) -> bool:
    return (getattr(bundle, "signal_kind", None) == SIGNAL_KIND
            or str(getattr(bundle, "event_id", "")).startswith(SIGNAL_KIND + ":"))


class RetainedAdvisory:
    """A retained bundle's own record, proven self-consistent; not current evidence."""

    def __init__(self, bundle: StoryBundle):
        try:
            record = bundle.raw_signal_dump["nhc_advisory"]
            if type(record) is not dict or record.get("schema") != SCHEMA:
                raise AdvisoryHold("nhc_advisory_retained_invalid")
            self.nomination = nomination(record["nomination"])
            raw = record["bulletin_utf8"].encode("ascii")
            bulletin = parse_bulletin(raw)
            self.bulletin = bulletin
            self.record = record
            hazard = bulletin.hazards.get(self.nomination.hazard)
            if (hazard is None or record["bulletin_sha256"] != digest(raw)
                    or [record["hazard"]["start"], record["hazard"]["end"]] != list(hazard)):
                raise AdvisoryHold("nhc_advisory_retained_invalid")
            if [record["place"]["start"], record["place"]["end"]] != list(place_span(bulletin, hazard,
                                                                                    self.nomination.place)):
                raise AdvisoryHold("nhc_advisory_retained_invalid")
            times = record["times"]
            self.captured_at = times["captured_at"]
            self.issued_at = bulletin.issued_at
            self.deadline = utc(times["operator_recheck_deadline"])
            expected_deadline = utc(self.captured_at) + timedelta(minutes=self.nomination.freshness_minutes)
            if (self.deadline != expected_deadline or times["issued_at"] != bulletin.issued_at
                    or times["upstream_expiry"] is not None
                    or times["upstream_expiry_status"] != UPSTREAM_EXPIRY_STATUS
                    or times["operator_recheck_rule"] != OPERATOR_RULE):
                raise AdvisoryHold("nhc_advisory_retained_invalid")
            if record["index_row"]["issuance"] and utc(record["index_row"]["issuance"]) != utc(self.issued_at):
                raise AdvisoryHold("nhc_advisory_retained_invalid")
            # Rebuild every field from validated parts; unknown or extra fields are held.
            source, row = record["source"], record["index_row"]
            if (set(source) != _SOURCE_KEYS or set(row) != _ROW_KEYS
                    or not all(type(source[k]) is str for k in ("index_url", "advisory_url", "index_sha256",
                                                                 "page_sha256", "original_language"))
                    or not all(type(source[k]) is int and source[k] >= 0
                               for k in ("index_bytes", "page_bytes", "bulletin_start", "bulletin_end"))
                    or source["bulletin_end"] - source["bulletin_start"] != len(raw)
                    or not all(type(row[k]) is str for k in _ROW_KEYS)
                    or row["url"] not in (self.nomination.advisory_url, self.nomination.advisory_url[len(ORIGIN):])
                    or advisory_key(row["advNum"]) != advisory_key(bulletin.advisory)):
                raise AdvisoryHold("nhc_advisory_retained_invalid")
            expected = {
                "schema": SCHEMA, "assertion_kind": "attributed_forecast_not_observation",
                "nomination": self.nomination.as_dict(),
                "source": {**source, "index_url": INDEX_URL, "advisory_url": self.nomination.advisory_url,
                           "original_language": "en_by_fixed_product_identity"},
                "index_row": {**row, "id": self.nomination.storm_id.lower(), "binNumber": self.nomination.bin,
                              "name": bulletin.storm_name},
                "bulletin_utf8": raw.decode("ascii"), "bulletin_sha256": digest(raw),
                "product": {"wmo_header": bulletin.wmo_header, "awips_id": bulletin.awips_id, "title": bulletin.title,
                            "storm_kind": bulletin.storm_kind, "storm_name": bulletin.storm_name,
                            "advisory": bulletin.advisory, "atcf_id": bulletin.atcf_id},
                "times": {"issued_at": bulletin.issued_at, "captured_at": self.captured_at, "upstream_expiry": None,
                          "upstream_expiry_status": UPSTREAM_EXPIRY_STATUS,
                          "operator_recheck_deadline": iso(expected_deadline), "operator_recheck_rule": OPERATOR_RULE},
                "hazard": {"key": self.nomination.hazard, "start": hazard[0], "end": hazard[1],
                           "text": bulletin.text(hazard)},
                "place": {"name": self.nomination.place, "start": record["place"]["start"],
                          "end": record["place"]["end"]},
                "context": [{"start": s, "end": e, "text": bulletin.text((s, e))} for s, e in bulletin.context],
            }
            rebuilt = _bundle(expected, bulletin, self.nomination)
            if (json.dumps(expected, sort_keys=True) != json.dumps(record, sort_keys=True)
                    or capture_bundle(rebuilt) != capture_bundle(bundle)):
                raise AdvisoryHold("nhc_advisory_retained_invalid")
        except AdvisoryHold:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, BundleCaptureError):
            raise AdvisoryHold("nhc_advisory_retained_invalid") from None

    def identity(self) -> dict:
        return {"storm_id": self.nomination.storm_id, "bin": self.nomination.bin,
                "advisory": self.bulletin.advisory, "issued_at": self.bulletin.issued_at,
                "bulletin_sha256": self.record["bulletin_sha256"], "hazard": self.nomination.hazard,
                "hazard_span": [self.record["hazard"]["start"], self.record["hazard"]["end"]],
                "place": self.nomination.place, "country": self.nomination.country}

    def check_times(self, now) -> None:
        check_times(self.issued_at, self.captured_at, self.deadline, now)
