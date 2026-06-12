"""Compact last-good readings for slow-moving sources."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from typing import Any, cast

from src.state_schema import BotState
from src.two_bot.json_utils import json_default

MAX_PAYLOAD_BYTES = 2_048


@dataclass(frozen=True)
class LastGoodReading:
    source_key: str
    data_date: str
    captured_at: str
    payload: dict[str, Any]
    from_cache: bool = True


def write(
    bot_state: BotState | MutableMapping[str, Any],
    source_key: str,
    data_date: str | date,
    payload: Mapping[str, Any],
    *,
    captured_at: str | datetime | None = None,
) -> None:
    """Store one compact derived reading for a slow-moving source."""

    source = str(source_key).strip()
    if not source:
        raise ValueError("last-good source_key must be non-empty")
    if not isinstance(payload, Mapping):
        raise ValueError("last-good payload must be a dict")

    normalized_date = _coerce_date(data_date)
    normalized_captured_at = _coerce_timestamp(captured_at)
    encoded = _payload_json(payload)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"last-good payload for {source} exceeds {MAX_PAYLOAD_BYTES} bytes"
        )

    state_dict = cast(MutableMapping[str, Any], bot_state)
    rows = state_dict.setdefault("last_good_readings", {})
    if not isinstance(rows, MutableMapping):
        rows = {}
        state_dict["last_good_readings"] = rows
    rows[source] = {
        "data_date": normalized_date,
        "captured_at": normalized_captured_at,
        "payload": json.loads(encoded),
    }


def read(
    bot_state: Mapping[str, Any],
    source_key: str,
    *,
    max_age_days: int,
    now: str | date | datetime | None = None,
) -> LastGoodReading | None:
    """Return a fresh cached reading, or None if absent/stale/malformed."""

    rows = bot_state.get("last_good_readings")
    if not isinstance(rows, Mapping):
        return None
    entry = rows.get(source_key)
    if not isinstance(entry, Mapping):
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None

    try:
        data_date = _coerce_date(entry.get("data_date"))
        captured_at = _coerce_timestamp(entry.get("captured_at"))
    except ValueError:
        return None

    if (_coerce_now_date(now) - date.fromisoformat(data_date)).days > max_age_days:
        return None

    return LastGoodReading(
        source_key=source_key,
        data_date=data_date,
        captured_at=captured_at,
        payload=deepcopy(payload),
        from_cache=True,
    )


def _payload_json(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            payload,
            default=json_default,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("last-good payload must be JSON-serializable") from exc


def _coerce_date(value: object) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid last-good data_date: {value!r}") from exc
    return parsed.isoformat()


def _coerce_timestamp(value: str | datetime | None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid last-good captured_at: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _coerce_now_date(value: str | date | datetime | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
