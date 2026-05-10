"""Typed source-fetch failures for alert telemetry."""

from __future__ import annotations


class SourceFetchError(RuntimeError):
    """A source fetch failed due to transport, schema, or parse problems."""


class SourceSkipped(RuntimeError):
    """A source was intentionally skipped, usually missing optional config."""
