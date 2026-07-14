"""NWS (National Weather Service) severe weather alerts.

Free API, no auth required.
Docs: https://www.weather.gov/documentation/services-web-api

Editorial note: We ONLY track the rarest, genuinely-newsworthy tiers.
Tornado warnings in tornado alley in April are routine — we skip them.
The remaining events are either Emergency-tier (catastrophic) or
hurricane-related (rare by definition).

NWS does NOT emit "Flash Flood Emergency"/"Tornado Emergency" as
``properties.event`` values. Emergencies ride ordinary Warning products:
event="Flash Flood Warning" with flashFloodDamageThreat=["CATASTROPHIC"]
and "FLASH FLOOD EMERGENCY" wording; event="Tornado Warning" with
tornadoDamageThreat=["CATASTROPHIC"] / "TORNADO EMERGENCY" wording
(verified against api.weather.gov during the 2026-07-10 Missouri flash
flood — see tests/fixtures/nws_cap_missouri_2026_07_10.json). Warnings
carrying an emergency designation are promoted here; routine Warnings
stay skipped. Upgrades arrive as messageType=Update, so the fetch
includes updates and admits them through the emergency path only.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

NWS_URL = "https://api.weather.gov/alerts/active"

# Sentinel key set in ``lifecycle_out`` when the payload is paginated
# (truncated): a partial payload is not a lifecycle census, and the runner
# must not retire pending drafts against it.
CENSUS_INCOMPLETE_KEY = "__census_incomplete__"

# ONLY truly rare, always-newsworthy events. If it happens every week in
# some part of the US, it's not in this list. Tornado Warnings in tornado
# alley in April are routine — we skip them and only keep Tornado Emergency.
TRACKED_EVENTS = {
    # The two emergency tiers never arrive as literal event values — NWS
    # encodes them as Warnings + damage-threat/wording, matched by
    # _emergency_designation() below. Kept defensively in case NWS ever
    # promotes them to first-class event types.
    "Tornado Emergency",      # Extremely rare, catastrophic tornado confirmed
    "Flash Flood Emergency",  # Extremely rare, catastrophic flooding
    "Hurricane Warning",      # Hurricanes themselves are rare, each one is news
    "Extreme Wind Warning",   # Only issued for major hurricane eyewalls (115+ mph)
    "Storm Surge Warning",    # Hurricane-specific, rare
    # Winter-tier extremes (rare, high-impact, not the routine Winter Storm Warning):
    "Blizzard Warning",       # Sustained 35+ mph winds + <1/4 mi visibility for 3+ hrs
    "Ice Storm Warning",      # 1/4+ inch ice accumulation — regional havoc
    "Extreme Cold Warning",   # NWS' upper-tier dangerous-cold designation
    # Heat-tier extreme. Overlaps Open-Meteo detection somewhat, but NWS
    # issues this only at genuinely dangerous levels (heat index 115F+).
    "Extreme Heat Warning",
}

# Warning products that carry the emergency tiers via a damage-threat
# parameter or emergency wording. Pairing is strict per event — a TORFF
# Flash Flood Warning may *mention* the co-located TORNADO EMERGENCY
# without being one.
_EMERGENCY_SPECS = {
    "Flash Flood Warning": (
        "flashFloodDamageThreat", "FLASH FLOOD EMERGENCY", "Flash Flood Emergency",
    ),
    "Tornado Warning": (
        "tornadoDamageThreat", "TORNADO EMERGENCY", "Tornado Emergency",
    ),
}
# The product's own affirmative declaration — attributive references to
# nearby PDS products ("a Particularly Dangerous Situation tornado watch")
# don't carry the leading "THIS IS A".
_PDS_PHRASE = "THIS IS A PARTICULARLY DANGEROUS SITUATION"
_PDS_DESIGNATION = "Particularly Dangerous Situation"

# Server-side event filter: every tracked event plus the Warning products
# that can carry an emergency designation. Keeps the alert+update payload
# small (verified live 2026-07-13: 28 features vs 333 unfiltered) and away
# from the API's collection limit during outbreaks. Sorted for a
# deterministic query.
_EVENT_FILTER = ",".join(sorted(TRACKED_EVENTS | set(_EMERGENCY_SPECS)))


@dataclass
class SevereWeatherAlert:
    event_type: str
    area: str
    severity: str
    headline: str
    event_id: str
    description: str = ""
    max_wind_gust: str = ""   # e.g. "75 mph"
    max_hail_size: str = ""   # e.g. "2.00 IN"
    tornado_detection: str = ""  # "RADAR INDICATED" or "OBSERVED"
    sender_name: str = ""     # e.g. "NWS Topeka KS"
    # "Flash Flood Emergency" / "Tornado Emergency" / "Particularly
    # Dangerous Situation" when the Warning carries that designation.
    emergency_designation: str = ""


def fetch_alerts(
    *, strict: bool = False, lifecycle_out: dict[str, int] | None = None
) -> list[SevereWeatherAlert]:
    """Fetch active severe weather alerts from NWS.

    ``lifecycle_out``, when given, is filled with the CURRENT tier of every
    emergency-capable warning lifecycle seen in the payload (base id → 2
    emergency / 1 PDS / 0 retired-by-downgrade). The runner reconciles
    pending drafts against it; a lifecycle ABSENT from the map was
    cancelled or expired. Left untouched when the fetch fails.
    """
    try:
        resp = fetch_with_retry(
            NWS_URL,
            # Updates are fetched too: emergency upgrades arrive as
            # messageType=Update mid-lifecycle (the 2026-07-10 Missouri
            # emergency re-issuances were all Updates). Cancels join the
            # lifecycle census so a same-payload withdrawal of an alert
            # issued in error retires it. Only the emergency path below
            # emits candidates from them.
            params={
                "status": "actual",
                "message_type": "alert,update,cancel",
                "event": _EVENT_FILTER,
            },
            headers={
                "User-Agent": "(theheat-bot, contact@theheat.app)",
                "Accept": "application/geo+json",
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"NWS payload is not an object: {type(data).__name__}")
        features = data.get("features")
        if not isinstance(features, list):
            # Schema drift, not a quiet day — treating a featureless 200 as
            # an empty census would falsely retire every pending emergency.
            raise ValueError(
                f"NWS payload without a features list: {type(features).__name__}"
            )

        alerts = []
        payload_dates = []
        seen_events = set()
        # One warning appears several times in a payload — Alert plus
        # Updates, tiers moving both ways, and superseded messages linger
        # in /alerts/active (verified live: 37 of 224 lifecycles appeared
        # more than once). Emergency-capable Warnings therefore coalesce
        # per lifecycle key; entries hold (rank, alert-or-None).
        lifecycles: dict[str, tuple[tuple[datetime, int], SevereWeatherAlert | None]] = {}
        # Guard against SPLIT identities: office/event group → whether each
        # member carried VTEC. A mix means one warning's messages key under
        # two different lifecycles and evictions stop working. Deliberately
        # DAY-FREE (unlike the fallback key): a 23:59 emergency and its
        # 00:01 VTEC-less downgrade are one warning.
        identity_kinds: dict[str, set[bool]] = {}

        for feature in features:
            props = feature.get("properties", {})
            payload_dates.append(
                props.get("sent") or props.get("effective") or props.get("onset")
            )
            event = props.get("event", "")
            # A missing messageType reads as an initial issuance: the real
            # API always sends it (every captured message did); synthetic
            # payloads lean permissive, and only the TRACKED path keys on
            # it — the emergency path is messageType-independent.
            message_type = props.get("messageType", "Alert")
            headline = props.get("headline", "") or ""
            description = props.get("description", "") or ""
            # Rich structured parameters — NWS includes wind gusts, hail
            # size, tornado type, and the damage-threat emergency tags.
            # Validate the RAW value: `or {}` would launder falsy junk
            # ([] / "") past the identity guard below.
            raw_parameters = props.get("parameters")
            if raw_parameters is None:
                parameters = {}
            elif isinstance(raw_parameters, dict):
                parameters = raw_parameters
            elif event in _EMERGENCY_SPECS:
                # An emergency-capable feature that lost its parameters
                # lost its lifecycle identity (VTEC) — degrading it to a
                # fallback key could leave an older emergency live under
                # a different key. Fail the payload; the next healthy
                # fetch self-heals. (Absent parameters are legitimate;
                # junk of any truthiness is not.)
                raise ValueError(
                    f"emergency-capable feature with non-mapping parameters: {event}"
                )
            else:
                # A drifted TRACKED feature has no identity at stake — don't
                # let it cost the cycle the rest of the payload.
                parameters = {}

            designation = _emergency_designation(event, parameters, headline, description)
            if designation and _vtec_all_terminal(parameters):
                # Expiration/cancellation products (every VTEC action
                # terminal) announce the END of a warning, never a live
                # emergency. The message still retires its lifecycle below.
                designation = ""

            severity = props.get("severity", "Unknown")
            area = props.get("areaDesc", "Unknown area")
            sender_name = props.get("senderName", "") or ""
            nws_id = props.get("id", "")
            max_wind_gust = _first_param(parameters, "maxWindGust")
            max_hail_size = _first_param(parameters, "maxHailSize")
            tornado_detection = _first_param(parameters, "tornadoDetection")

            if designation or event in _EMERGENCY_SPECS:
                # Lifecycle-aware coalescing: EVERY message of an
                # emergency-capable warning participates. The latest
                # message decides the tier (ties go to the higher tier) —
                # a latest message with no designation retires the
                # lifecycle: NWS downgraded the warning, and a
                # present-tense emergency draft would be stale.
                #
                # Ids dedup on the VTEC event tracking number: every
                # re-issuance shares it while each CAP message gets a
                # fresh id — without it, each Update would re-draft. A
                # missing/unparseable VTEC (not observed on real
                # FF.W/TO.W products) degrades to an office+event+day
                # key, never to per-message ids. A PDS-tier id is
                # suffixed so a later catastrophic upgrade re-drafts —
                # the upgrade is the news.
                sent = props.get("sent") or ""
                vtec_id = _vtec_event_id(parameters, sent)
                # Office identity for grouping: senderName is a mutable
                # display string, so the WMO station (e.g. KLSX) joins it —
                # a VTEC-less message whose senderName also drifted must
                # still group with its warning.
                wmo = _first_param(parameters, "WMOidentifier").split()
                office_keys = {sender_name, wmo[1] if len(wmo) > 1 else ""} - {""}
                if not vtec_id and not office_keys:
                    if designation:
                        # A designated message that cannot be tied to any
                        # lifecycle: fail closed — it is a real emergency
                        # we cannot key.
                        raise ValueError(
                            f"emergency-capable feature without VTEC or office identity: {event}"
                        )
                    # An identity-less ROUTINE message emits nothing and
                    # can't retire anything — skip it. If it superseded an
                    # emergency, the old message leaves /alerts/active and
                    # absence-based reconciliation retires the draft next
                    # cycle.
                    continue
                base_id = vtec_id or _emergency_fallback_id(sender_name, event, sent)
                for office_key in office_keys:
                    identity_kinds.setdefault(f"{office_key}:{event}", set()).add(
                        bool(vtec_id)
                    )
                tier = 0
                alert = None
                if designation:
                    tier = 1 if designation == _PDS_DESIGNATION else 2
                    alert = SevereWeatherAlert(
                        event_type=event,
                        area=_simplify_area(area),
                        severity=severity,
                        headline=headline,
                        event_id=base_id + (":pds" if tier == 1 else ""),
                        description=description[:500],  # cap description length
                        max_wind_gust=max_wind_gust,
                        max_hail_size=max_hail_size,
                        tornado_detection=tornado_detection,
                        sender_name=sender_name,
                        emergency_designation=designation,
                    )
                rank = (_message_dt(props), tier)
                existing = lifecycles.get(base_id)
                if existing is not None:
                    if _UNKNOWN_TIME in (rank[0], existing[0][0]):
                        # Ordering decides evictions: with two messages of
                        # one warning, an unparseable time could let an
                        # older emergency beat a newer downgrade. (A
                        # single-message lifecycle makes no ordering
                        # decision and stays permissive.)
                        raise ValueError(
                            f"emergency-capable lifecycle without a parseable timestamp: {base_id}"
                        )
                    if rank[0] == existing[0][0] and rank[1] != existing[0][1]:
                        # Minute-resolution timestamps: a same-instant pair
                        # with DIFFERENT tiers is an ambiguous correction —
                        # (time, tier) ranking would silently keep the
                        # higher tier. Fail closed.
                        raise ValueError(
                            f"conflicting tiers at one instant: {base_id}"
                        )
                if existing is None or rank > existing[0]:
                    lifecycles[base_id] = (rank, alert)
                continue

            if event not in TRACKED_EVENTS or message_type != "Alert":
                # Tracked events enter at initial issuance only; an Update
                # is the same warning re-issued under a fresh message id.
                continue

            # Use NWS-provided ID for stable dedup; fall back to position-based
            if nws_id:
                event_id = f"nws_{nws_id}"
            else:
                event_id = f"nws_{event.replace(' ', '_').lower()}_{date.today().isoformat()}_{len(alerts)}"

            # Deduplicate by event type + area (NWS sends many alerts per storm)
            dedup_key = f"{event}_{_simplify_area(area)}"
            if dedup_key in seen_events:
                continue
            seen_events.add(dedup_key)

            alerts.append(SevereWeatherAlert(
                event_type=event,
                area=_simplify_area(area),
                severity=severity,
                headline=headline,
                event_id=event_id,
                description=description[:500],  # cap description length
                max_wind_gust=max_wind_gust,
                max_hail_size=max_hail_size,
                tornado_detection=tornado_detection,
                sender_name=sender_name,
                emergency_designation=designation,
            ))

        mixed = sorted(
            group for group, kinds in identity_kinds.items() if len(kinds) > 1
        )
        if mixed:
            # One warning's messages split between a VTEC key and the
            # office/event/day fallback — a downgrade under one key cannot
            # evict the emergency under the other, leaving a false
            # present-tense emergency. Fail closed; the next healthy fetch
            # self-heals.
            raise ValueError(f"mixed VTEC/fallback lifecycle identity: {mixed[:3]}")

        alerts.extend(alert for _, alert in lifecycles.values() if alert is not None)

        if newest_date := newest_freshness_date(payload_dates):
            assert_freshness(newest_date, "nws_alerts", max_age_days=1)

        # Filled only once the payload passed every validation — a failed
        # fetch must never look like a census.
        if lifecycle_out is not None:
            for base_id, ((_, tier), _alert) in lifecycles.items():
                lifecycle_out[base_id] = tier
            pagination = data.get("pagination")
            if isinstance(pagination, dict) and pagination.get("next"):
                lifecycle_out[CENSUS_INCOMPLETE_KEY] = 1
        return alerts

    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"NWS alerts fetch failed: {exc}") from exc
        return []


def _first_param(parameters: dict, key: str) -> str:
    """NWS parameters are dict[str, list]. Return the first value or empty string."""
    val = parameters.get(key)
    if isinstance(val, list) and val:
        return str(val[0])
    if isinstance(val, str):
        return val
    return ""


def _emergency_designation(
    event: str, parameters: dict, headline: str, description: str
) -> str:
    """The NWS emergency tier riding an ordinary Warning product, or "".

    Promotes on the CATASTROPHIC damage-threat parameter, or on emergency
    wording in the product's OWN headline surfaces (properties.headline +
    parameters.NWSheadline) — never the narrative description, which can
    reference a co-located product or announce a downgrade ("the FLASH
    FLOOD EMERGENCY ... has ended"). NWS rewrites NWSheadline on
    downgrade (the de-escalated 2026-07-10 MO message reads "FLASH FLOOD
    WARNING REMAINS IN EFFECT..." while every emergency message led with
    "FLASH FLOOD EMERGENCY FOR...").

    PDS promotes one tier lower and needs BOTH the product's own
    affirmative declaration (narrative included — that is where NWS puts
    the boilerplate) AND the event's own damage-threat tag. Literal
    emergency event values (should NWS ever emit them) designate
    themselves.
    """
    if event in ("Flash Flood Emergency", "Tornado Emergency"):
        return event
    spec = _EMERGENCY_SPECS.get(event)
    if spec is None:
        return ""
    threat_param, emergency_phrase, designation = spec
    raw_threat = parameters.get(threat_param)
    threat_values = raw_threat if isinstance(raw_threat, list) else [raw_threat]
    if any(str(value).upper() == "CATASTROPHIC" for value in threat_values if value):
        return designation
    own_headlines = f"{headline} {_first_param(parameters, 'NWSheadline')}".upper()
    if emergency_phrase in own_headlines:
        return designation
    has_own_threat_tag = any(
        str(value).upper() in ("CONSIDERABLE", "CATASTROPHIC")
        for value in threat_values
        if value
    )
    if has_own_threat_tag and _PDS_PHRASE in f"{own_headlines} {description.upper()}":
        return _PDS_DESIGNATION
    return ""


# VTEC actions that terminate (or hand off) a warning rather than
# continue it: cancellation, upgrade-transition, expiration.
_TERMINAL_VTEC_ACTIONS = ("CAN", "UPG", "EXP")


def _parsed_vtec(parameters: dict) -> list[list[str]]:
    """P-VTEC codes as split parts. Real CAP can pack several codes into
    one newline-delimited value — split before parsing or a terminated
    code shadows the active one."""
    raw = parameters.get("VTEC")
    values = raw if isinstance(raw, list) else [raw] if raw else []
    codes = [
        line.strip() for value in values for line in str(value).splitlines() if line.strip()
    ]
    parsed = []
    for code in codes:
        parts = code.strip("/").split(".")
        if len(parts) >= 6 and all(parts[2:6]):
            parsed.append(parts)
    return parsed


def _vtec_all_terminal(parameters: dict) -> bool:
    """True when every VTEC action is terminal — an expiration or
    cancellation product, not a live warning."""
    parsed = _parsed_vtec(parameters)
    return bool(parsed) and all(parts[1] in _TERMINAL_VTEC_ACTIONS for parts in parsed)


# Sentinel for a message without a parseable instant. Tolerable for a
# single-message lifecycle; two-message ordering fails closed on it.
_UNKNOWN_TIME = datetime.min.replace(tzinfo=UTC)


def _message_dt(props: dict) -> datetime:
    """The message's instant, for lifecycle ordering. Normalized to UTC —
    around DST changes one office's local-time strings do not sort
    lexically. Unparseable/absent times sort first (never newest)."""
    for field in ("sent", "effective", "onset"):
        raw = props.get(field)
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return _UNKNOWN_TIME


def _vtec_event_id(parameters: dict, sent: str) -> str:
    """Lifecycle-stable id from the VTEC event tracking number, or "".

    ``/O.EXT.KLSX.FF.W.0050.…/`` → ``nws_vtec:KLSX.FF.W.0050:<year>``.
    Only the ``nws_`` prefix carries an underscore: two_bot.memory's
    ``_event_base`` truncates ids to their first three underscore-separated
    parts when grouping recent tweets, and must see the full key.

    Segment transitions can list a terminated code (CAN/UPG/EXP) alongside
    the active one — prefer the active warning. ETNs reset yearly and are
    reused across forecast offices, so office and year stay in the key.
    The year comes from ``sent``: a warning extended across New Year's
    midnight re-keys once — an acceptable rare duplicate draft; keying
    without the year would suppress next year's reuse of the same ETN.
    """
    parsed = _parsed_vtec(parameters)
    if not parsed:
        return ""
    active = [parts for parts in parsed if parts[1] not in _TERMINAL_VTEC_ACTIONS]
    office, phenomena, significance, etn = (active[0] if active else parsed[0])[2:6]
    year = sent[:4] if sent[:4].isdigit() else str(date.today().year)
    return f"nws_vtec:{office}.{phenomena}.{significance}.{etn}:{year}"


def _emergency_fallback_id(sender_name: str, event: str, sent: str) -> str:
    """Day-scoped office+event key for a designated Warning without a
    usable VTEC. Holds one emergency's lifecycle to one candidate — CAP
    ``references`` link only each message's immediate predecessor
    (verified on the 2026-07-10 MO thread), so no chain walk can recover
    the original message id. Two distinct same-office same-day emergencies
    would collapse; rare-on-rare beats re-drafting every Update of one
    emergency. A lifecycle spanning local midnight re-keys once (one
    duplicate draft, behind manual review) — accepted: this path needs a
    VTEC-less FF.W/TO.W product, which no real capture has shown, and a
    persisted cross-run alias is not worth that tail.
    """
    day = sent[:10] if len(sent) >= 10 else date.today().isoformat()
    office = (sender_name or "unknown-office").replace(" ", "-")
    return f"nws_emergency:{office}:{event.replace(' ', '-')}:{day}"


def _simplify_area(area: str) -> str:
    """Simplify NWS area descriptions (they can be very long lists of counties)."""
    # NWS areas look like "Tulsa, OK; Rogers, OK; Creek, OK; ..."
    # Take first area and state
    parts = area.split(";")
    if len(parts) <= 2:
        return area.strip()
    # Return first county + state with count
    first = parts[0].strip()
    return f"{first} and {len(parts) - 1} other areas"
