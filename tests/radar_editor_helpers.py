"""Genuine retained invented radar source; shared unchanged fixture provenance."""
import pytest
from src.commands import postgres_published_media as published
from src.commands.schema import utc_text
from tests import published_radar_fixtures as f
from tests import test_postgres_synchronous_generation as sync
from tests import test_postgres_sourced_generation as sourced, test_postgres_editor_media as editor

@pytest.fixture
def radar_case(store, core, monkeypatch, tmp_path, native_dependencies):
    from src.voice import safety

    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "invented-offline-key")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-offline-key")
    core[2].initialize_synchronous_checks(now=sourced.NOW)
    bundle = f.bundle(monkeypatch, at=sourced.NOW)
    value = dict(
        schema_version=1,
        source_key="nws_alerts",
        source_revision="invented-tornado-alert-one",
        captured_at=utc_text(sourced.NOW),
        useful_until="2026-09-29T12:30:00Z",
        urgent=True,
        bundle=bundle.to_dict(),
        save=dict(
            legacy_type=bundle.signal_kind,
            event_id=bundle.event_id,
            score=None,
            city="",
            tweet_date="",
            cooldown_exempt=False,
            review_context=None,
            evaluator_metadata=None,
        ),
    )
    refs = store.retain_generation_input(value)
    reserve = store.retain_generation_reservation(
        sourced.allowance_document(
            refs["brief_id"],
            schema_version=2,
            execution_mode="synchronous",
            samples=1,
            max_attempts=1,
            read_budget_seconds=180,
        )
    )
    config = dict(
        schema_version=2,
        current_inputs=[refs["brief_id"]],
        reservations=dict(batch=None, synchronous=reserve),
    )
    store.configure_sourced_generation(lambda: config)
    case = dict(
        store=store,
        refs=refs,
        value=value,
        config=config,
        bundle=bundle,
        text="The NWS has issued a tornado warning for the invented test area.",
    )
    assert sourced.request(case)["status"] == "applied"
    sent, factory = sync.transport(case)
    assert sourced.run(case, "write", factory)["outcome"] == "response_retained"
    sync.checked(case, monkeypatch)
    assert len(sent) == 1
    core[2].initialize_media_staging()
    core[2].initialize_media_commands()
    core[2].initialize_revision_checks(now=editor.AT)
    store.configure_editor_media(**native_dependencies, scratch=tmp_path / "native")
    doc, raw, references, receipt = f.input_document(at=sourced.NOW)
    retained = published.retain(store, doc, raw, references, receipt)
    selection = dict(schema_version=1, selections={refs["brief_id"]: retained["input_sha256"]})
    published.configure(store, lambda: selection)
    case.update(
        radar_input=doc,
        original=raw,
        reference_bytes=references,
        receipt_bytes=receipt,
        published_config=selection,
        provider_requests=sent,
    )
    return case
