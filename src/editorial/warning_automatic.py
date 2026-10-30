"""Default-off automatic TEXT for typed official-warning families.

Three supported families each have their own exact-``"1"`` flag; all are OFF
by default and Root alone flips them:

- ``nhc_advisory``      THEHEAT_NHC_ADVISORY_AUTO_TEXT    (fixed NHC products, CLI-installed owner)
- ``official_warning``  THEHEAT_OFFICIAL_WARNING_AUTO_TEXT (explicitly supplied packet owner)
- ``severe_weather``    THEHEAT_NWS_WARNING_AUTO_TEXT     (fixed NWS active-alerts feed)

A flag only selects a typed ``armed_auto`` approval policy at admission. It is
never a review pass: the ordinary writer/fact-check/critic, the existing
current-source owners (re-read at admission, due handling and the final send
boundary), the 200-scalar text cap, publication policy/epoch and final safety
all still apply. This module adds the warning-specific automatic rules:

- text only (no attachment), production not paused;
- qualified consequence copy against a typed brief built from the retained
  official evidence: attributed, modal, no observed-harm upgrade, no consequence
  or category the source does not state, and storm motion never presented as
  wind intensity (or the reverse);
- episode/update rules across drafts and the publish ledger: an unknown prior
  delivery blocks; a repeat or older update is not re-published; an update whose
  official statement is unchanged (tier/category only) is not material; a newer
  admitted update supersedes an older pending one. Issuer identity is part of
  every episode key, so cross-border sources never merge by place name.

Any hold keeps the draft for ordinary manual review; nothing is rewritten.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
import re
from typing import Any

FAMILIES: dict[str, dict[str, str]] = {
    "nhc_advisory": {"flag": "THEHEAT_NHC_ADVISORY_AUTO_TEXT", "policy_key": "nhc_advisory_auto_text",
                     "inventory_key": "nhc_advisory_auto_text_enabled", "owner": "nhc_advisory_owner (CLI scope)",
                     "current_source": "two fixed NHC products re-read at admission, due and send"},
    "official_warning": {"flag": "THEHEAT_OFFICIAL_WARNING_AUTO_TEXT", "policy_key": "official_warning_auto_text",
                         "inventory_key": "official_warning_auto_text_enabled",
                         "owner": "explicit WarningSource scope (absent unless supplied)",
                         "current_source": "supplied owner re-resolved at admission, due and send"},
    "severe_weather": {"flag": "THEHEAT_NWS_WARNING_AUTO_TEXT", "policy_key": "nws_warning_auto_text",
                       "inventory_key": "nws_warning_auto_text_enabled", "owner": "fixed NWS active-alerts feed",
                       "current_source": "active feed re-read before safety and after the durable intent"},
}
AUTO_DELAY_MINUTES = 30
HOLD_MESSAGES = {
    "warning_auto_text_disabled": "Automatic text for this warning family is off.",
    "warning_auto_production_paused": "Production is paused.",
    "warning_auto_text_only": "Automatic warning posts are text only.",
    "warning_auto_source_invalid": "The retained official evidence is unreadable.",
    "warning_auto_qualifier_missing": "The copy must name the issuer and keep the warning/forecast wording.",
    "warning_auto_observed_harm_claim": "The copy reports harm the official warning does not state.",
    "warning_auto_unsupported_consequence": "The copy adds a consequence or category the source does not state.",
    "warning_auto_unsupported_speed": "The copy states a speed the source does not state.",
    "warning_auto_motion_intensity_conflated": "The copy presents storm motion as wind intensity (or the reverse).",
    "warning_prior_delivery_unknown": "An earlier delivery in this warning episode is unknown; reconcile first.",
    "warning_episode_already_published": "This or a newer official update was already published.",
    "warning_update_not_material": "The official statement is unchanged since publication (tier/category only).",
    "warning_superseded_by_newer_update": "A newer official update supersedes this draft.",
    "warning_episode_identity_invalid": "The warning episode identity cannot be established.",
}
_OBSERVED_HARM = re.compile(
    r"\b(?:killed|kills|deaths?|died|dead|destroyed|damaged|flooded|swept away|stranded|injured|injuries|"
    r"(?:has|have|had) (?:caused|left|brought|triggered)|caused)\b", re.IGNORECASE)
_TEMPLATE_CONSEQUENCE = re.compile(
    r"\b(?:life[- ]threatening|catastrophic|devastating|deadly|dangerous|destructive|historic|unprecedented|"
    r"extreme|major disaster)\b", re.IGNORECASE)
_CATEGORY = re.compile(r"\bcat(?:egory)?\.?\s*([1-5])\b", re.IGNORECASE)
_SPEED = re.compile(r"(\d{1,3}(?:\.\d)?)\s*(mph|km/h|kph|kt|kts|knots)\b", re.IGNORECASE)
_MOTION = re.compile(r"\b(?:mov\w*|motion|movement|travel\w*|heading|drift\w*|forward speed)\b", re.IGNORECASE)
_INTENSITY = re.compile(r"\b(?:winds?|gusts?|gusting|sustained)\b", re.IGNORECASE)
_MODALITY = re.compile(r"\b(?:warns?|warning|watch|advisory|forecasts?|forecast to|expected|could|may|might|"
                       r"possible|likely|risk)\b", re.IGNORECASE)
_UNITS = {"mph": "mph", "km/h": "kmh", "kph": "kmh", "kt": "kt", "kts": "kt", "knots": "kt"}


def _env(environ: Any = None) -> Any:
    return os.environ if environ is None else environ


def auto_text_enabled(kind: Any, environ: Any = None) -> bool:
    return isinstance(kind, str) and kind in FAMILIES and _env(environ).get(FAMILIES[kind]["flag"]) == "1"


POLICY_KEYS = frozenset(family["policy_key"] for family in FAMILIES.values())


def governs(draft: Any) -> bool:
    """Only drafts armed by this feature's typed policy; other bindings keep their existing gates."""
    policy = draft.get("approval_policy") if isinstance(draft, dict) else None
    return (isinstance(policy, dict) and policy.get("key") in POLICY_KEYS
            and draft.get("type") in FAMILIES and FAMILIES[draft["type"]]["policy_key"] == policy.get("key"))


def approval_policy_fields(kind: Any, environ: Any = None) -> dict[str, Any] | None:
    """Typed armed_auto policy for an enabled family, else None (the manual policy stays)."""
    if not auto_text_enabled(kind, environ):
        return None
    return {"key": FAMILIES[kind]["policy_key"], "mode": "armed_auto",
            "recommended_delay_minutes": AUTO_DELAY_MINUTES, "can_auto_approve": True,
            "reason": "Opt-in official-warning text; current-source, episode and qualified-copy rules gate "
                      "arming and every send."}


def inventory_flags(environ: Any = None) -> dict[str, bool]:
    return {family["inventory_key"]: auto_text_enabled(kind, environ) for kind, family in FAMILIES.items()}


def runtime_projection(environ: Any = None) -> dict[str, dict[str, Any]]:
    """What Operations shows: per family flag, policy, owner and current-source boundary."""
    return {kind: {"flag": family["flag"], "enabled": auto_text_enabled(kind, environ),
                   "policy_key": family["policy_key"] if auto_text_enabled(kind, environ) else None,
                   "owner": family["owner"], "current_source": family["current_source"],
                   "manual_review": "always_available"} for kind, family in FAMILIES.items()}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def draft_bundle(draft: Any) -> dict | None:
    review = draft.get("review_context") if isinstance(draft, dict) else None
    two = review.get("two_bot") if isinstance(review, dict) else None
    bundle = two.get("bundle") if isinstance(two, dict) else None
    return bundle if isinstance(bundle, dict) else None


def _speeds(text: str) -> list[dict[str, Any]]:
    out = []
    for match in _SPEED.finditer(text):
        before = text[max(0, match.start() - 60):match.start()]
        # The nearest preceding cue word decides the class.
        cues = [(m.end(), "storm_motion") for m in _MOTION.finditer(before)] + \
               [(m.end(), "wind_intensity") for m in _INTENSITY.finditer(before)]
        klass = max(cues)[1] if cues else "unclassified"
        out.append({"value": float(match[1]), "unit": _UNITS[match[2].lower()], "class": klass})
    return out


def consequence_brief(kind: str, bundle: dict) -> dict[str, Any]:
    """Typed, attributed brief from retained official evidence only (raises on malformed evidence)."""
    raw = bundle["raw_signal_dump"]
    if kind == "nhc_advisory":
        record = raw["nhc_advisory"]
        selected = record["nomination"]
        statements = [{"text": record["hazard"]["text"], "class": "forecast_threat"}] + [
            {"text": row["text"], "class": "source_context"} for row in record["context"]]
        corpus = record["bulletin_utf8"]
        names = ["NHC", "National Hurricane Center"]
        timing = {"issued_at": record["times"]["issued_at"],
                  "operator_recheck_deadline": record["times"]["operator_recheck_deadline"],
                  "upstream_expiry": None}
        places = [{"name": selected["place"], "country": selected["country"]}]
        episode: dict[str, Any] = {"key": ["nhc", selected["storm_id"].lower(), selected["hazard"], selected["place"].casefold(),
                           selected["country"]],
                   "rank": _advisory_rank(record["product"]["advisory"]),
                   "statement_sha256": _sha(record["hazard"]["text"]), "issuer": "nhc"}
        tier = f"{record['product']['storm_kind']} {record['product']['storm_name']}"
    elif kind == "official_warning":
        packet = json.loads(raw["official_warning"]["metadata_utf8"])
        statements = [{"text": packet["warning"]["text"], "class": "forecast_threat"}]
        corpus = raw["official_warning"]["source_utf8"]
        names = [raw["source_name"]]
        timing = {"issued_at": packet["issued_at"], "valid_until": packet["valid_until"]}
        places = [{"name": packet["place"]["name"], "country": packet["place"]["country"]}]
        episode = {"key": [packet["issuer_id"], packet["report_id"], packet["place"]["name"].casefold(),
                           packet["place"]["country"]],
                   "rank": None, "statement_sha256": _sha(packet["warning"]["text"]), "issuer": packet["issuer_id"]}
        tier = None
    elif kind == "severe_weather":
        envelope = raw["source_evidence"]
        props = envelope["feature"]["properties"]
        texts = [str(props.get(name) or "") for name in ("headline", "description", "instruction")]
        statements = [{"text": text, "class": "forecast_threat"} for text in texts if text]
        corpus = "\n".join(texts)
        names = ["NWS", "National Weather Service"] + ([props["senderName"]] if props.get("senderName") else [])
        timing = {"issued_at": props.get("sent"), "expires": props.get("expires"), "ends": props.get("ends")}
        places = [{"name": str(props.get("areaDesc") or ""), "country": "US"}]
        alert_id = props.get("id") or envelope.get("source_alert_id")
        if not isinstance(alert_id, str) or not alert_id:
            raise ValueError("nws_alert_identity_missing")
        references = props.get("references") or []
        if not isinstance(references, list) or any(not isinstance(row, dict) or not isinstance(row.get("identifier"), str)
                                                  or not row["identifier"] for row in references):
            raise ValueError("nws_references_invalid")
        episode = {"key": ["nws", alert_id],
                   "official_ids": sorted({alert_id, *(row["identifier"] for row in references)}),
                   "rank": _sent_rank(props.get("sent")), "statement_sha256": _sha(str(props.get("description") or "")),
                   "issuer": "nws"}
        tier = str(props.get("event") or "") or None
    else:
        raise ValueError("warning family unsupported")
    return {"family": kind, "assertion": "attributed_forecast_threat_not_observed_harm",
            "attribution_names": names, "statements": statements, "timing": timing, "places": places,
            "tier": tier, "speeds": _speeds(corpus),
            "source_consequence_terms": sorted({m.group().casefold() for m in _TEMPLATE_CONSEQUENCE.finditer(corpus)}),
            "source_categories": sorted({m[1] for m in _CATEGORY.finditer(corpus)}),
            "source_harm_terms": sorted({m.group().casefold() for m in _OBSERVED_HARM.finditer(corpus)}),
            "episode": episode, "lead": "one short complete lead; keep issuer attribution and warning modality"}


def writer_consequence_view(bundle: Any) -> dict[str, Any] | None:
    """Derived prompt view; internal integrity only, never current-source authority.

    Existing pipeline owners still establish source authenticity and currentness.
    This reads no owner or transport and never changes captured bundle bytes.
    """
    kind = getattr(bundle, "signal_kind", None)
    if kind not in FAMILIES:
        return None
    from src.two_bot.bundle_capture import capture_bundle
    payload = capture_bundle(bundle).payload()
    raw = payload["raw_signal_dump"]
    if kind == "nhc_advisory":
        from src.two_bot.intern.nhc_advisory import RetainedAdvisory
        RetainedAdvisory(bundle)
    elif kind == "severe_weather":
        from src.media.published_radar import source_envelope
        envelope = raw["source_evidence"]
        if envelope != source_envelope(envelope["feature"], envelope["captured_at"]):
            raise ValueError("nws_retained_evidence_changed")
        if payload["event_id"] != "nws_" + envelope["source_alert_id"]:
            raise ValueError("nws_retained_identity_changed")
    else:
        retained = raw["official_warning"]
        metadata, original = retained["metadata_utf8"], retained["source_utf8"]
        packet = json.loads(metadata)
        if _sha(metadata) != retained["metadata_sha256"] or _sha(original) != packet["content_sha256"]:
            raise ValueError("warning_retained_evidence_changed")
        from src.editorial.official_warning import _origin
        identity = {"schema": "theheat.warning-evidence/v1", "metadata_sha256": _sha(metadata),
                    "content_sha256": _sha(original), "issuer_id": packet["issuer_id"],
                    "issuer_name": raw["source_name"], "origin": _origin(packet["source_url"]),
                    "report_id": packet["report_id"], "revision": packet["revision"],
                    "original_language": packet["original_language"]}
        evidence_sha = _sha(json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        if evidence_sha != retained["evidence_sha256"]:
            raise ValueError("warning_retained_attribution_changed")
        anchor = packet["warning"]
        if original.encode()[anchor["start"]:anchor["end"]] != anchor["text"].encode():
            raise ValueError("warning_retained_anchor_changed")
    brief = consequence_brief(kind, payload)
    # The writer receives only the selected hazard/context; global bulletin term
    # inventories remain copy floors, not a license to import another place's impact.
    return {key: brief[key] for key in ("family", "assertion", "attribution_names", "statements", "timing", "places", "lead")}


def _advisory_rank(value: str) -> list:
    match = re.fullmatch(r"0*([0-9]{1,3})([A-Z]?)", str(value))
    if match is None:
        raise ValueError("advisory number invalid")
    return [int(match[1]), match[2]]


def _sent_rank(value: Any) -> list:
    if not isinstance(value, str):
        raise ValueError("sent time invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("sent time invalid")
    return [parsed.astimezone(UTC).isoformat()]


def copy_hold(text: Any, brief: dict[str, Any]) -> str | None:
    """Automatic-only necessary bindings; entailment remains the ordinary required checks' job."""
    if not isinstance(text, str) or not text.strip():
        return "warning_auto_qualifier_missing"
    harm = {m.group().casefold() for m in _OBSERVED_HARM.finditer(text)}
    if harm - set(brief["source_harm_terms"]):
        return "warning_auto_observed_harm_claim"
    consequence = {m.group().casefold() for m in _TEMPLATE_CONSEQUENCE.finditer(text)}
    if consequence - set(brief["source_consequence_terms"]):
        return "warning_auto_unsupported_consequence"
    if {m[1] for m in _CATEGORY.finditer(text)} - set(brief["source_categories"]):
        return "warning_auto_unsupported_consequence"
    source: dict[tuple[float, str], set[str]] = {}
    for row in brief["speeds"]:
        source.setdefault((row["value"], row["unit"]), set()).add(row["class"])
    for row in _speeds(text):
        classes = source.get((row["value"], row["unit"]))
        if classes is None:
            return "warning_auto_unsupported_speed"
        known = classes - {"unclassified"}
        if row["class"] != "unclassified" and known and row["class"] not in known:
            return "warning_auto_motion_intensity_conflated"
    if not any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE)
               for name in brief["attribution_names"] if name):
        return "warning_auto_qualifier_missing"
    rest = text
    for name in brief["attribution_names"] + [place["name"] for place in brief["places"]]:
        if name:
            rest = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", "", rest, flags=re.IGNORECASE)
    if _MODALITY.search(rest) is None:
        return "warning_auto_qualifier_missing"
    return None


def _episode(draft: Any) -> tuple[str, dict] | None:
    if not isinstance(draft, dict) or draft.get("type") not in FAMILIES:
        return None
    bundle = draft_bundle(draft)
    if bundle is None:
        return None
    try:
        return draft["type"], consequence_brief(draft["type"], bundle)["episode"]
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _cmp(left: Any, right: Any) -> int:
    if left is None or right is None:
        return 0
    return (left > right) - (left < right)


def episode_hold(draft: dict, state: Any) -> str | None:
    """Existing event/ledger identities: first publication or a material newer update; unknown blocks."""
    current = _episode(draft)
    if current is None:
        return "warning_episode_identity_invalid"
    kind, mine = current
    state = state if isinstance(state, dict) else {}
    ledger = state.get("publish_ledger") if isinstance(state.get("publish_ledger"), dict) else {}
    posted = set(state.get("posted_events") or [])
    linked_ids = set(mine.get("official_ids", []))
    if kind == "severe_weather":
        # Follow only explicit CAP references, including an intermediate saved
        # update. Area/name similarity never establishes a relationship.
        known = [_episode(other) for other in state.get("drafts") or []]
        while True:
            expanded = set(linked_ids)
            for entry in known:
                if entry is not None and entry[0] == kind:
                    ids = set(entry[1].get("official_ids", []))
                    if ids & linked_ids:
                        expanded.update(ids)
            if expanded == linked_ids:
                break
            linked_ids = expanded
        for identifier in linked_ids:
            prior = ledger.get("nws_" + identifier)
            if isinstance(prior, dict) and not prior.get("tweet_id") and prior.get("phase") != "not_sent":
                return "warning_prior_delivery_unknown"
    own = ledger.get(draft.get("event_id"))
    if isinstance(own, dict) and not own.get("tweet_id") and own.get("phase") != "not_sent":
        return "warning_prior_delivery_unknown"
    for other in state.get("drafts") or []:
        if not isinstance(other, dict) or other is draft or other.get("id") == draft.get("id"):
            continue
        theirs = _episode(other)
        if theirs is None or theirs[0] != kind or (
                not (set(theirs[1].get("official_ids", [])) & linked_ids) if kind == "severe_weather"
                else theirs[1]["key"] != mine["key"]):
            continue  # Different issuer/family/place: never merged by a name coincidence.
        event_id = other.get("event_id")
        row = ledger.get(event_id)
        if isinstance(row, dict) and not row.get("tweet_id") and row.get("phase") != "not_sent":
            return "warning_prior_delivery_unknown"
        order = _cmp(theirs[1]["rank"], mine["rank"])
        published = other.get("status") == "posted" or event_id in posted or (
            isinstance(row, dict) and bool(row.get("tweet_id")))
        if published:
            if order >= 0 or event_id == draft.get("event_id"):
                return "warning_episode_already_published"
            if theirs[1]["statement_sha256"] == mine["statement_sha256"]:
                return "warning_update_not_material"
        elif other.get("status") in {"pending", "approved"} and order > 0:
            return "warning_superseded_by_newer_update"
    if draft.get("event_id") in posted or (isinstance(own, dict) and own.get("tweet_id")):
        return "warning_episode_already_published"
    return None


def runner_fence(kind: str, bundle: Any, state: Any) -> str | None:
    """Before buying a writer: an unknown delivery or an unchanged published statement adds no candidate."""
    if not isinstance(bundle, dict):
        from src.two_bot.bundle_capture import capture_bundle
        try:
            bundle = capture_bundle(bundle).payload()
        except Exception:  # noqa: BLE001 - an unreadable bundle has no episode identity
            return "warning_episode_identity_invalid"
    raw = bundle
    probe = {"id": "_runner_probe", "type": kind, "event_id": raw.get("event_id"),
             "review_context": {"two_bot": {"bundle": raw}}}
    hold = episode_hold(probe, state)
    return hold if hold in {"warning_prior_delivery_unknown", "warning_update_not_material"} else None


def auto_text_hold(draft: Any, state: Any = None, now: datetime | None = None) -> str | None:
    """Every warning automatic-text rule for one saved draft; None when eligible.

    Current-source currency is not decided here: the existing family owners are
    called at admission and at every send boundary, so this adds no source read.
    ``state`` None or empty skips the cross-draft episode rules (final boundary).
    """
    del now  # Times are the existing owners' rules; kept for a uniform hook signature.
    kind = draft.get("type") if isinstance(draft, dict) else None
    if not auto_text_enabled(kind):
        return "warning_auto_text_disabled"
    if os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1":
        return "warning_auto_production_paused"
    if any(key in draft for key in ("media_attachment", "hot10_rows", "media_selection")):
        return "warning_auto_text_only"
    bundle = draft_bundle(draft)
    try:
        brief = consequence_brief(str(kind), bundle) if bundle is not None else None
    except (KeyError, TypeError, ValueError, AttributeError):
        brief = None
    if brief is None:
        return "warning_auto_source_invalid"
    hold = copy_hold(draft.get("text"), brief)
    if hold is not None:
        return hold
    if isinstance(state, dict) and state:
        return episode_hold(draft, state)
    return None


def operator_view(draft: Any) -> dict[str, Any]:
    """Read-only inspection for a held draft: brief, current hold and the manual path."""
    kind = draft.get("type") if isinstance(draft, dict) else None
    bundle = draft_bundle(draft)
    brief = None
    if kind in FAMILIES and bundle is not None:
        try:
            brief = consequence_brief(str(kind), bundle)
        except (KeyError, TypeError, ValueError, AttributeError):
            brief = None
    hold = (draft.get("automatic_source_hold") if isinstance(draft, dict) else None) or None
    return {"family": kind, "automatic_enabled": auto_text_enabled(kind), "hold": hold,
            "hold_message": HOLD_MESSAGES.get(str(hold)) if hold else None, "brief": brief,
            "manual_review": "available", "post_error": draft.get("post_error") if isinstance(draft, dict) else None}


__all__ = ["AUTO_DELAY_MINUTES", "FAMILIES", "HOLD_MESSAGES", "POLICY_KEYS", "governs", "approval_policy_fields", "auto_text_enabled",
           "auto_text_hold", "consequence_brief", "copy_hold", "draft_bundle", "episode_hold", "inventory_flags",
           "operator_view", "runner_fence", "runtime_projection"]
