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
    "scripts/runtime_report.py", "scripts/gen_runtime_report_workflow.py",
    ".github/workflows/bot.yml", ".github/workflows/runtime-report.yml", "src/runtime_inventory.py",
    "dashboard/lib/runtime-report.js", "dashboard/lib/runtime-inventory.js", "dashboard/lib/state-store.js", "dashboard/lib/publication-control.js",
    "dashboard/app/api/config/route.js", "dashboard/app/api/dashboard/route.js", "dashboard/app/api/drafts/route.js",
    "dashboard/lib/nws-source-timing.js", "dashboard/lib/nws-warning-evidence.js",
    "src/two_bot/important_variants.py", "src/two_bot/batch_contract.py",
    "src/commands/postgres_important_variants.py",
    "src/commands/postgres_cost_projection.py", "src/two_bot/retained_usage.py",
    "src/media/published_radar.py",
    "src/commands/postgres_published_media.py",
    "src/data/nws_alerts.py",
    "src/orchestrator/sources/nws_alerts.py",
    "src/storage/ghcn_runtime_inputs.py",
    "src/commands/postgres_ghcn_source_results.py",
    "src/orchestrator/ghcn_source_result_client.py",
    "src/two_bot/ghcn_claim_view.py",
    "src/data/ghcn_db.py",
    "src/data/temperature_history.py",
    "scripts/threshold_artifacts.py",
    "src/orchestrator/common.py",
    "src/state.py",
    "src/storage/hosted_staging.py", "src/storage/postgres_projection.py",
    "src/storage/scientific_supply.py", "src/commands/preview_ingress.py",
    "src/commands/hosted_fixture.py", "src/commands/bulk_rejection_client.py",
    "src/commands/postgres_source_results.py", "src/orchestrator/source_result_client.py",
    "src/storage/cyclone_supply.py", "src/storage/physical_events.py",
    "src/orchestrator/cyclone_episodes.py", "src/orchestrator/cyclones.py",
    "src/editorial/newsworthiness.py", "src/editorial/report_development.py",
    "src/editorial/portfolio.py",
    "src/storage/retained_reports.py", "src/commands/postgres_report_development.py",
    "src/evaluation/coverage.py", "src/commands/postgres_coverage.py",
    "src/orchestrator/sources/newsworthiness.py",
    "src/data/places.py", "data/place_registry.json", "data/country_codes.json",
    "src/commands/postgres_batch_results.py", "src/commands/postgres_checks.py",
    "src/commands/check_execution_journal.py", "src/two_bot/check_executor.py",
    "src/two_bot/check_requests.py", "src/two_bot/check_transport.py",
    "src/two_bot/candidate_derivation.py",
    "src/commands/check_journal.py", "src/commands/batch_result_journal.py",
    "src/config.py", "src/editorial/policy.py", "src/editorial/revisions.py",
    "src/orchestrator/posting.py", "src/orchestrator/nws_publication.py", "src/media/attachment.py", "src/media/review_packet.py",
    "dashboard/lib/editorial-policy.js", "dashboard/lib/draft-revisions.js",
    "dashboard/lib/saved-claim-evidence.js",
    "src/two_bot/writer.py", "src/two_bot/critic.py", "src/two_bot/fact_check.py",
    "src/two_bot/trial_budget.py",
    "src/two_bot/pipeline.py", "src/two_bot/provider_preflight.py", "src/two_bot/memory.py", "src/two_bot/types.py",
    "src/two_bot/strict_contract.py", "src/two_bot/evidence_contract.py",
    "src/two_bot/scientific_claims.py", "src/two_bot/json_utils.py",
    "src/two_bot/air_quality_claims.py",
    "src/two_bot/bundle_capture.py",
    "src/two_bot/source_links.py", "src/orchestrator/two_bot_dispatch.py",
    "src/two_bot/multisignal.py",
    "src/two_bot/rejected_candidate.py",
    "src/voice/safety.py", "src/data/temperature_evidence.py",
    "src/editorial/approval.py", "src/data/world_thresholds.py", "src/data/open_meteo.py",
    "src/data/ghcn.py", "src/data/ghcn_format.py", "src/data/gdacs.py", "src/data/nhc.py", "src/data/cyclones.py",
    "src/commands/postgres_check_observations.py",
    "src/commands/postgres_media.py", "src/commands/media_journal.py",
    "src/storage/migrations/009_media_staging.sql",
    "src/commands/postgres_media_commands.py", "src/storage/migrations/010_media_commands.sql",
    "src/commands/schema.py", "src/commands/reducer.py", "src/media/joint_review.py", "src/media/platform_description.py",
    "src/commands/postgres_authority.py", "src/commands/sqlite_authority.py",
    "src/commands/postgres_delivery.py", "src/commands/preview_delivery_worker.py",
    "src/posting/local_delivery.py", "src/posting/delivery_transport.py", "src/posting/delivery_receipts.py",
    "src/posting/twitter.py", "src/posting/bluesky.py", "src/storage/migrations/012_local_delivery.sql",
    "src/storage/migrations/014_preview_delivery.sql",
    "src/orchestrator/sources/open_meteo.py",
    "src/orchestrator/sources/air_quality.py",
    "src/data/ocean_sst_anomaly.py", "src/data/crw_contract.py",
    "src/data/coral_dhw.py", "src/data/coral_evidence.py", "src/data/coral_source_contract.py", "src/data/coral_regional_contract.py",
    "src/data/air_quality.py", "src/data/air_quality_availability.py", "src/data/air_quality_contract.py", "src/data/air_quality_evidence.py",
    "src/data/firms.py", "src/data/fire_source_contract.py", "src/data/fire_identity.py", "src/data/fire_evidence.py",
    "src/editorial/draft_admission.py", "src/orchestrator/dedup.py",
    "src/commands/postgres_candidate_admission.py",
    "src/commands/postgres_sourced_generation.py", "src/two_bot/sourced_generation.py",
    "src/commands/postgres_synchronous_generation.py", "src/commands/postgres_sync_checks.py",
    "src/two_bot/synchronous_writer.py", "src/two_bot/synchronous_origin.py", "src/storage/migrations/013_synchronous_checks.sql",
    "src/commands/postgres_revision_checks.py", "src/commands/postgres_editor_media.py",
    "src/commands/preview_media_worker.py", "src/storage/migrations/011_saved_revision_checks.sql",
    "src/commands/submission_recovery.py",
    "src/media/native_profile.py",
    "src/two_bot/check_origin.py",
    "src/two_bot/batch_authority.py", "src/two_bot/batch_transport.py", "src/two_bot/batch_collector.py",
    "src/orchestrator/draft_save.py", "src/orchestrator/sources/firms.py", "src/orchestrator/triage_queue.py",
    "src/editorial/synthesis.py", "src/editorial/thresholds.py",
    "src/editorial/marine_evidence.py",
    "src/orchestrator/sources/ocean_sst_anomaly.py", "src/orchestrator/sources/coral_dhw.py",
    "src/orchestrator/sources/synthesis.py",
    "src/media/crw_graphic_adapter.py", "src/media/evidence_graphic.py",
    "src/media/air_quality_graphic_adapter.py",
    "src/media/fire_graphic_adapter.py",
    "src/media/fire_map_graphic_adapter.py",
    "src/media/viirs_map_graphic_adapter.py",
    "src/media/maps/ne_110m_land_v4_1_0.json", "src/media/maps/manifest.json", "src/media/maps/NOTICE.md",
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
                     for module in (writer, critic, fact_check, safety)},
                     "writer_schema": writer.WRITER_OUTPUT_SCHEMA, "fact_check_schema": fact_check.FACT_CHECK_OUTPUT_SCHEMA,
                     "safety_request_config": {"max_output_tokens": safety.SAFETY_MAX_OUTPUT_TOKENS}}
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
