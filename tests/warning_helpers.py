"""Invented supplied-warning inputs, with no clock or global pytest plugin."""
from datetime import UTC, datetime
import hashlib
import json

from src.editorial.official_warning import SCHEMA, WarningNomination

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
WARNING = "INVENTED: Example Island is under a wind warning; dangerous winds are possible tonight."


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def anchor(raw, text):
    start = raw.index(text.encode())
    return {"start": start, "end": start + len(text.encode()), "text": text}


def packet():
    raw = ("INVENTED official bulletin, not real weather.\n" + WARNING + "\n").encode()
    metadata = {"schema": SCHEMA, "issuer_id": "fixture-agency", "report_id": "fixture-warning-1",
        "revision": "r1", "source_url": "https://warnings.example.test/report/fixture-1",
        "content_sha256": sha(raw), "issued_at": "2026-10-29T11:00:00Z",
        "captured_at": "2026-10-29T11:02:00Z", "valid_until": "2026-10-30T00:00:00Z",
        "original_language": "en", "translation": None, "warning": anchor(raw, WARNING),
        "place": {"name": "Example Island", "country": "ZZ", "anchor": anchor(raw, "Example Island")}}
    return metadata, raw


def nomination(metadata_bytes, raw):
    metadata = json.loads(metadata_bytes)
    return WarningNomination(issuer_id="fixture-agency", issuer_name="Invented Warning Agency",
        origin="https://warnings.example.test", report_id="fixture-warning-1",
        revision=metadata.get("revision", "r1"), metadata_sha256=sha(metadata_bytes),
        content_sha256=sha(raw), original_language="en")
