"""Current editorial policy identity, independent of content and send receipts.

The bot reads its actual loaded model settings and current policy source files.
A historical runtime inventory is never an authorization source in Python.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from src.editorial.revisions import fingerprint

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILES = (
    "src/config.py", "src/editorial/policy.py", "src/editorial/revisions.py",
    "src/orchestrator/posting.py",
    "dashboard/lib/editorial-policy.js", "dashboard/lib/draft-revisions.js",
    "src/two_bot/writer.py", "src/two_bot/critic.py", "src/two_bot/fact_check.py",
    "src/two_bot/pipeline.py", "src/two_bot/memory.py", "src/two_bot/types.py",
    "src/two_bot/strict_contract.py", "src/two_bot/evidence_contract.py",
    "src/two_bot/scientific_claims.py", "src/two_bot/json_utils.py",
    "src/voice/safety.py", "src/data/temperature_evidence.py",
    "src/editorial/approval.py", "src/data/world_thresholds.py", "src/data/open_meteo.py",
    "src/data/ghcn.py", "src/data/ghcn_format.py", "src/orchestrator/sources/open_meteo.py",
)
MODEL_KEYS = {"writer", "writer_provider", "fact_check", "critic", "safety"}
FLAG_KEYS = {"critic_enabled", "critic_revise_enabled", "writer_samples", "safety_llm_enabled"}


def source_manifest() -> dict:
    files = set(POLICY_FILES)
    for folder in ("src/two_bot/prompts", "src/two_bot/intern"):
        files.update(str(path.relative_to(ROOT)) for path in (ROOT / folder).glob("*.py"))
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(files)}
    return {"schema_version": 1, "source_sha256": fingerprint(sources), "files": sources}


def valid_policy(value) -> bool:
    if not isinstance(value, dict) or set(value) != {"schema_version", "source_sha256", "execution_sha256", "models", "flags"}:
        return False
    execution = value.get("execution_sha256")
    sha, models, flags = value.get("source_sha256"), value.get("models"), value.get("flags")
    return (type(value.get("schema_version")) is int and value["schema_version"] == 1
            and isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
            and isinstance(execution, str) and len(execution) == 64 and all(c in "0123456789abcdef" for c in execution)
            and isinstance(models, dict) and set(models) == MODEL_KEYS
            and all(isinstance(v, str) and 0 < len(v) <= 160 for v in models.values())
            and isinstance(flags, dict) and set(flags) == FLAG_KEYS
            and all(type(flags[k]) is bool for k in FLAG_KEYS - {"writer_samples"})
            and type(flags["writer_samples"]) is int and 1 <= flags["writer_samples"] <= 100)


def current_editorial_policy() -> dict | None:
    """Recompute from this process; inability to establish policy fails closed."""
    try:
        from src.two_bot import critic, fact_check, pipeline, writer
        from src.voice import safety
        execution = {"prompts": {module.__name__: {name: text for name, text in vars(module).items()
                     if name.isupper() and isinstance(text, str) and ("PROMPT" in name or "GUIDANCE" in name)}
                     for module in (writer, critic, fact_check)},
                     "writer_schema": writer.WRITER_OUTPUT_SCHEMA, "fact_check_schema": fact_check.FACT_CHECK_OUTPUT_SCHEMA}
        value = {"schema_version": 1, "execution_sha256": fingerprint(execution), "source_sha256": source_manifest()["source_sha256"],
                 "models": {"writer": writer.WRITER_MODEL, "writer_provider": writer.WRITER_PROVIDER,
                            "fact_check": fact_check.FACT_CHECKER_MODEL, "critic": critic.CRITIC_MODEL,
                            "safety": safety.GEMINI_SAFETY_MODEL},
                 "flags": {"critic_enabled": pipeline._critic_enabled(),
                           "critic_revise_enabled": pipeline._critic_revise_enabled(),
                           "writer_samples": pipeline._writer_samples(),
                           "safety_llm_enabled": bool(safety.GEMINI_API_KEY)}}
        return value if valid_policy(value) else None
    except (OSError, ValueError, TypeError, UnicodeError, ImportError):
        return None
