"""Process-local current-warning input, never reconstructed from packet labels.

Only an explicit trusted owner can supply this context. There is no environment
file, HTTP upload, URL lookup, global registry, provider call or default resolver.
Separate editor/sender processes need their own explicit current-source input;
missing context holds this lane rather than trusting a saved source as current.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
import os
import re

from src.editorial.official_warning import WarningHold, WarningNomination
from src.two_bot.bundle_capture import BundleCapture, capture_bundle
from src.two_bot.intern.warnings import build_warning_bundle
from src.two_bot.types import StoryBundle


@dataclass(frozen=True)
class SuppliedWarning:
    metadata_bytes: bytes
    source_bytes: bytes
    nomination: WarningNomination


@dataclass(frozen=True)
class WarningSource:
    """Injected source owner; resolve must read its independently current input."""

    resolve: Callable[[], SuppliedWarning | None]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


_CURRENT: ContextVar[WarningSource | None] = ContextVar("current_official_warning_source", default=None)
_PROVIDER_INPUT: ContextVar[tuple[BundleCapture, bool] | None] = ContextVar("warning_provider_input", default=None)


@contextmanager
def warning_source_scope(source: WarningSource) -> Iterator[None]:
    if type(source) is not WarningSource or not callable(source.resolve) or not callable(source.clock):
        raise WarningHold("warning_source_configuration_invalid")
    token = _CURRENT.set(source)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def is_warning(bundle: StoryBundle) -> bool:
    return (getattr(bundle, "signal_kind", None) == "official_warning"
            or str(getattr(bundle, "event_id", "")).startswith("official_warning:"))


def current_warning_bundle() -> StoryBundle:
    current = _CURRENT.get()
    if current is None:
        raise WarningHold("warning_current_source_unavailable")
    try:
        selected = current.resolve()
        if type(selected) is not SuppliedWarning:
            raise WarningHold("warning_current_source_unavailable")
        return build_warning_bundle(selected.metadata_bytes, selected.source_bytes,
            nomination=selected.nomination, now=current.clock())
    except WarningHold:
        raise
    except Exception:
        # Callback exceptions can contain private source/path/credential text.
        raise WarningHold("warning_current_source_unavailable") from None


def _named(text: str, name: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", text.casefold()) is not None


def guard_warning_generation_settings() -> None:
    # The existing pipeline owns these settings. Read them without changing any
    # global flag, model or retry policy. Import only at execution, not startup.
    from src.two_bot import pipeline
    if pipeline._writer_samples() != 1 or pipeline._critic_revise_enabled() or not pipeline._critic_enabled():
        raise WarningHold("warning_requires_one_sample_no_revise_and_required_critic")


def begin_warning_provider_scope(bundle: StoryBundle, captured: BundleCapture, *,
                                 generating: bool = True) -> Token:
    return _PROVIDER_INPUT.set((captured, generating) if is_warning(bundle) else None)


def end_warning_provider_scope(token: Token | None) -> None:
    if token is not None:
        _PROVIDER_INPUT.reset(token)


def guard_warning_provider_attempt() -> None:
    """Before reservation/archive intent/SDK, including each existing retry."""
    bound = _PROVIDER_INPUT.get()
    if bound is None:
        return
    captured, generating = bound
    # Use the immutable original capture, not a callback-mutated live bundle.
    guard_warning_story(StoryBundle(**captured.payload()), generating=generating)
    if generating:
        guard_warning_generation_settings()


@contextmanager
def warning_final_safety_scope(draft: dict | None) -> Iterator[None]:
    context = (draft or {}).get("review_context")
    two = context.get("two_bot") if isinstance(context, dict) else None
    raw = two.get("bundle") if isinstance(two, dict) else None
    warning = ((draft or {}).get("type") == "official_warning"
        or str((draft or {}).get("event_id", "")).startswith("official_warning:")
        or (isinstance(raw, dict) and raw.get("signal_kind") == "official_warning"))
    bound = None
    if warning:
        if not isinstance(raw, dict):
            raise WarningHold("warning_retained_source_invalid")
        try:
            bundle = StoryBundle(**raw)
            bound = (capture_bundle(bundle), False)
        except (TypeError, ValueError):
            raise WarningHold("warning_retained_source_invalid") from None
    # Mask a nested warning context for an unrelated manual publication, then
    # restore it. Null legacy two_bot metadata must retain its prior behavior.
    token = _PROVIDER_INPUT.set(bound)
    try:
        yield
    finally:
        end_warning_provider_scope(token)


def guard_warning_story(bundle: StoryBundle, *, candidate: str | None = None,
                        generating: bool = True) -> None:
    """Cheap current-input check, never a required model check or approval."""
    if not is_warning(bundle):
        return
    if generating and os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1":
        raise WarningHold("warning_generation_paused")
    expected = current_warning_bundle()
    if capture_bundle(bundle) != capture_bundle(expected):
        raise WarningHold("warning_current_source_changed")
    if candidate is not None:
        if type(candidate) is not str or not candidate.strip():
            raise WarningHold("warning_copy_invalid")
        if not _named(candidate, expected.raw_signal_dump["source_name"]):
            raise WarningHold("warning_copy_attribution_missing")
        if not _named(candidate, expected.where):
            raise WarningHold("warning_copy_place_missing")
        modality = candidate.casefold()
        for name in (expected.raw_signal_dump["source_name"], expected.where):
            modality = re.sub(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", "", modality)
        if re.search(r"\b(?:warns?|warning|watch|advisory|forecasts?)\b", modality) is None:
            raise WarningHold("warning_copy_modality_missing")
        # Necessary bindings only. Entailment, invented impacts/consequences and
        # forecast-to-observation upgrades still require the ordinary checks.


def current_warning_source(draft: dict | None) -> str | None:
    """Sender/source-review hold. A saved packet is not a current resolver."""
    if not isinstance(draft, dict):
        return None
    context = draft.get("review_context") or {}
    two = context.get("two_bot") if isinstance(context, dict) else None
    raw = two.get("bundle") if isinstance(two, dict) else None
    warning = (draft.get("type") == "official_warning"
        or str(draft.get("event_id", "")).startswith("official_warning:")
        or (isinstance(raw, dict) and raw.get("signal_kind") == "official_warning"))
    if not warning:
        return None
    try:
        if context.get("official_warning_source_hold"):
            raise WarningHold("warning_saved_source_held")
        if not isinstance(raw, dict) or draft.get("type") != "official_warning" or (
            draft.get("event_id") != raw.get("event_id") or raw.get("signal_kind") != "official_warning"
        ):
            raise WarningHold("warning_draft_identity_changed")
        guard_warning_story(StoryBundle(**raw), candidate=draft.get("text"), generating=False)
        return None
    except WarningHold as exc:
        return exc.code
    except (TypeError, ValueError, AttributeError):
        return "warning_retained_source_invalid"
