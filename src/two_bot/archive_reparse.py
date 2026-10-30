"""Deterministic offline re-parse of retained model responses through the real parsers.

Input is one verified private request archive (``request_archive_replay``).
For each retained call, the exact returned HTTP entity is decoded and handed to
the SAME production parser/interpreter the live stage uses. Nothing here calls
a model, fetches a source, reads Gist/DB state or writes anything: a replay
verdict is a parser outcome on retained bytes, never a new model verdict, fresh
source evidence, approval or publication eligibility.

A missing dimension yields a precise ``unsupported`` state instead of a guess:
no captured response, an undecodable entity, a stage without a pure parser, or
an admission check that needs inputs the archive does not retain. Parser
identity is reported both as archived (scope-open code hashes) and as run now,
so a changed parser is visible rather than silently re-judging old output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from src.two_bot.request_archive_replay import ArchiveInvalid, CallRecord, VerifiedArchive

READ_VERSION = 1
_ROOT = Path(__file__).resolve().parents[2]
# Stage -> (parser source file, pure parser). Fact check admission needs the
# tweet, bundle and checker state, so only its strict JSON parser is replayed.
_PARSER_FILES = {"writer": "src/two_bot/writer.py", "safety": "src/voice/safety.py",
                 "critic": "src/two_bot/critic.py", "fact_check": "src/two_bot/fact_check.py"}
_ADMISSION_MISSING = {"fact_check": ["tweet_text", "story_bundle", "checker_state"]}
MAX_CALLS = 128


def _writer(text: str) -> dict:
    from src.two_bot.writer import _parse_writer_json
    result = _parse_writer_json(text)
    return {"tweet_present": result.tweet is not None, "kill_code": getattr(result, "kill_code", None),
            "kill_reason_present": bool(getattr(result, "kill_reason", None))}


def _safety(text: str) -> dict:
    from src.voice.safety import interpret_response
    return {"decision": interpret_response(text)}


def _critic(text: str) -> dict:
    from src.two_bot.critic import _parse_critic_result
    result = _parse_critic_result(text)
    return {"verdict": result.verdict, "passed": bool(result.passed)}


def _fact_check(text: str) -> dict:
    from src.two_bot.fact_check import _parse_fact_check_json
    passed, failures, claims = _parse_fact_check_json(text, require_extracted_claims=True)
    return {"parser_passed": bool(passed), "parser_failures": len(failures), "extracted_claims": len(claims)}


_PARSERS: dict[str, Callable[[str], dict]] = {"writer": _writer, "safety": _safety, "critic": _critic,
                                              "fact_check": _fact_check}


def _file_sha(relative: str) -> str | None:
    try:
        return hashlib.sha256((_ROOT / relative).read_bytes()).hexdigest()
    except OSError:
        return None


def _response_text(provider: str, entity: Any) -> str | None:
    """The model text exactly as the live SDK would surface it; None if not a text answer."""
    if not isinstance(entity, dict):
        return None
    if provider == "anthropic":
        blocks = entity.get("content")
        if not isinstance(blocks, list):
            return None
        texts = [b.get("text") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(str(t) for t in texts) if texts and all(isinstance(t, str) for t in texts) else None
    if provider == "google":
        candidates = entity.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            return None
        parts = (candidates[0].get("content") or {}).get("parts")
        if not isinstance(parts, list):
            return None
        texts = [p.get("text") for p in parts if isinstance(p, dict) and "text" in p and not p.get("thought")]
        return "".join(str(t) for t in texts) if texts and all(isinstance(t, str) for t in texts) else None
    return None


def _unsupported(call: CallRecord, reason: str, **extra) -> dict:
    return {"call": call.number, "stage": call.stage, "provider": call.provider, "replay_state": "unsupported",
            "reason": reason, **extra}


def reparse_call(archive: VerifiedArchive, call: CallRecord) -> dict:
    parser_file = _PARSER_FILES.get(call.stage)
    if parser_file is None:
        return _unsupported(call, "stage_parser_not_replayable")
    archived = (((archive.opened or {}).get("code_identity") or {}).get("files") or {}).get(parser_file)
    current = _file_sha(parser_file)
    identity = {"parser_file": parser_file, "archived_sha256": archived, "current_sha256": current,
                "parser_changed": archived is None or archived != current}
    attempts = [a for a in call.attempts if a.response.availability == "captured" and a.response.artifact]
    if not attempts:
        return _unsupported(call, "response_not_captured", parser=identity, outcome=call.outcome)
    response = attempts[-1].response
    try:
        raw = archive.artifact(response.artifact)
        entity = json.loads(raw.decode("utf-8"))
    except (ArchiveInvalid, UnicodeDecodeError, ValueError):
        return _unsupported(call, "response_entity_undecodable", parser=identity)
    text = _response_text(call.provider, entity)
    if text is None:
        return _unsupported(call, "response_without_model_text", parser=identity,
                            raw_response_sha256=response.artifact)
    try:
        result = _PARSERS[call.stage](text)
        state, error = "reparsed", None
    except Exception as exc:  # The real parser refusing retained bytes is itself the replay outcome.
        result, state, error = None, "parser_refused", type(exc).__name__
    row = {"call": call.number, "stage": call.stage, "provider": call.provider, "model": call.model,
           "replay_state": state, "parser_error": error, "result": result, "parser": identity,
           "raw_response_sha256": response.artifact, "attempt": attempts[-1].attempt,
           "new_model_verdict": False, "fresh_source": False, "publication_eligible": False}
    missing = _ADMISSION_MISSING.get(call.stage)
    if missing:
        row["admission"] = {"replay_state": "unsupported", "reason": "admission_inputs_not_archived",
                            "missing": list(missing)}
    return row


def reparse_archive(archive: VerifiedArchive) -> dict:
    """Every retained call, in order; an invalid archive is refused, never partially trusted."""
    if getattr(archive, "status", None) == "invalid":
        raise ArchiveInvalid("archive_invalid")
    rows = [reparse_call(archive, call) for call in archive.calls[:MAX_CALLS]]
    states: dict[str, int] = {}
    for row in rows:
        states[row["replay_state"]] = states.get(row["replay_state"], 0) + 1
    return {"read_version": READ_VERSION, "archive_status": getattr(archive, "status", None),
            "calls": rows, "states": states, "truncated": len(archive.calls) > MAX_CALLS,
            "provider_io": "forbidden", "source_io": "forbidden", "new_model_verdicts": 0,
            "limitations": ["parser_outcome_on_retained_bytes_only", "not_a_model_verdict_or_fresh_source",
                            "never_publishes_or_approves_a_historical_candidate"]}


__all__ = ["reparse_archive", "reparse_call"]
