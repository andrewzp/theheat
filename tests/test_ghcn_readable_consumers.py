"""Joined, invented transport-only consumers; no model/source truth is claimed."""

from copy import deepcopy
from dataclasses import asdict
import json

from freezegun import freeze_time
import pytest

from src.editorial import revisions
from src.editorial.policy import current_editorial_policy
from src.orchestrator import triage_queue, two_bot_dispatch
from src.state import DEFAULT_STATE
from src.two_bot import batch_contract, check_requests, negative_cache, sourced_generation
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.candidate_derivation import derive_candidate
from src.two_bot.ghcn_readable_warrant import decode_wire, encode_full, prepare_bundle
from src.two_bot.memory import build_memory_slice
from src.two_bot.types import WriterResult
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.test_observed_copy_guard_journey import _models
from tests.test_refill import _score
from tests.test_ghcn_publication_observation_set import paired_variants as paired_variants
from tests.test_ghcn_readable_generation import _request_bundles
from tests.test_request_archive_sdk import (
    journey_env as journey_env,
    private_root,
    run_journey,
    writer_json,
    fact_json,
    critic_json,
)

NOW = "2026-09-09T12:00:00Z"
COPY = "Graphic Fixture reached 42.2°C on 8 September, its archive high in the available GHCN archive through 2026-09-07."


def source():
    return graphic_bundles(direction="high", tier="all_time")[-1]


def kwargs(bundle):
    return dict(
        bundle=bundle,
        score=_score(category="all_time_high"),
        source="ghcn",
        legacy_type="all_time_high",
        event_id=bundle.event_id,
        review_context={},
    )


@pytest.mark.parametrize("mode", ["legacy", "triage", "refill"])
@pytest.mark.parametrize("admission", ["source", "lower_level"])
def test_queue_drains_save_the_same_enriched_wire_that_cache_and_sdk_checked(
    monkeypatch, mode, admission
):
    from src.two_bot.types import TriageCandidateBundle
    from src.two_bot import multisignal

    models = _models(monkeypatch, copy=COPY)
    from src.two_bot import pipeline

    actual_generate = pipeline.generate_draft
    outcomes = []

    def observed_generate(*args, **kwargs):
        result = actual_generate(*args, **kwargs)
        outcomes.append(deepcopy(kwargs.get("result_out")))
        return result

    monkeypatch.setattr(pipeline, "generate_draft", observed_generate)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if mode == "triage" else "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
    monkeypatch.setenv("THEHEAT_MULTISIGNAL_CONTEXT", "1")
    monkeypatch.setattr(multisignal, "multisignal_context_enabled", lambda: True)

    # Optional enrichment is invented input, not a source/eligibility verdict.
    def enrich(queue):
        for candidate in queue:
            candidate.bundle.human_impact.append(
                dict(
                    claim="Invented retained context",
                    value=2,
                    source_name="Invented fixture",
                    url="https://example.invalid/context",
                    as_of="2026-09-09",
                )
            )

    monkeypatch.setattr(multisignal, "attach_related_signals", enrich)
    original_fingerprint = negative_cache.bundle_fingerprint
    seen = []

    def cache_input(bundle, state):
        seen.append(capture_bundle(bundle).payload())
        return original_fingerprint(bundle, state)

    monkeypatch.setattr(negative_cache, "bundle_fingerprint", cache_input)
    state = deepcopy(DEFAULT_STATE)
    bundle = source()
    with freeze_time(NOW, tick=True):
        if admission == "source":
            assert triage_queue._enqueue_story_candidate(state, **kwargs(bundle))
        else:
            triage_queue._enqueue_candidate(
                state,
                TriageCandidateBundle(
                    **kwargs(bundle), city="", tweet_date="", cooldown_exempt=False, created_at=NOW
                ),
            )
        assert triage_queue._drain_and_write_triage_queue(state, None) == 1, [
            row.get("kill_reason") for row in outcomes
        ]
    assert "_triage_queue" not in state
    [draft] = state["drafts"]
    wire = draft["review_context"]["two_bot"]["bundle"]
    assert (
        wire["human_impact"][0]["value"] == 2 and decode_wire(wire)["raw_signal_dump"]["evidence"]
    )
    assert seen and all(value == wire for value in seen)
    for stage, request in models.requests:
        if stage != "safety":
            assert list(_request_bundles(request)) == [wire]
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    assert draft["status"] == "pending" and not draft.get("tweet_id")


def test_direct_dispatch_prepares_before_async_submission_or_cache(monkeypatch):
    class Client:
        def submit(self, bundle, **_):
            self.wire = capture_bundle(bundle).payload()
            return {"queued": True}

    client = Client()
    bundle = source()
    state, outcome = deepcopy(DEFAULT_STATE), {}
    args = kwargs(bundle)
    args.pop("source")
    assert (
        two_bot_dispatch._try_two_bot_draft(
            bot_state=state, **args, generation_client=client, result_out=outcome
        )
        is False
    )
    assert decode_wire(client.wire)["event_id"] == bundle.event_id
    assert outcome == {"queued": True} and state["drafts"] == []


def test_retained_source_batch_derivation_and_required_requests_keep_wire_identity(monkeypatch):
    _models(monkeypatch, copy=COPY)
    state = deepcopy(DEFAULT_STATE)
    prepared = prepare_bundle(source())
    wire = capture_bundle(prepared).payload()
    restored = sourced_generation.source_bundle(wire)
    assert capture_bundle(restored).payload() == wire
    with freeze_time(NOW):
        memory = build_memory_slice(state, restored)
        policy = current_editorial_policy()
        plan = json.loads(
            batch_contract.prepare_batch_plan(
                bundle=restored,
                memory=memory,
                bundle_sha256=revisions.fingerprint(wire),
                memory_sha256=revisions.fingerprint(memory.to_dict()),
                policy=policy,
                job_id="invented-readable",
                publication_epoch="paused-invented",
                created_at=NOW,
                useful_until="2026-09-10T12:00:00Z",
                minimum_window_seconds=3600,
            )
        )
        candidate = asdict(
            WriterResult(
                tweet=COPY,
                kill_reason=None,
                angle_chosen="plain_number",
                era_anchor_used=None,
                peer_comparison_used=None,
                reasoning="Explicit invented provider response",
            )
        )
        candidate_id = revisions.fingerprint(candidate)
        derived = derive_candidate(candidate, candidate_id, wire, policy)
        packet = dict(
            schema_version=2,
            candidate=candidate,
            candidate_id=candidate_id,
            bundle=wire,
            memory=memory.to_dict(),
            checker_state=state,
            checker_state_sha256=revisions.fingerprint(state),
            policy=policy,
            check_date="2026-09-09",
            derivation=derived,
            derivation_id=revisions.fingerprint(derived),
            raw_candidate_id=candidate_id,
            text_sha256=derived["text_sha256"],
        )
        for stage in ("fact_check", "critic"):
            request = check_requests.prepare_request(packet, stage)
            assert list(_request_bundles(request)) == [wire]
        assert check_requests.deterministic_result(packet)["passed"]
    assert plan["bundle_sha256"] == revisions.fingerprint(wire)
    assert list(_request_bundles(plan["requests"])) == [wire]
    changed = deepcopy(wire)
    changed["country"] = "Changed retained enrichment"
    with pytest.raises(ValueError):
        batch_contract.prepare_batch_plan(
            bundle=sourced_generation.source_bundle(changed),
            memory=memory,
            bundle_sha256=revisions.fingerprint(wire),
            memory_sha256=revisions.fingerprint(memory.to_dict()),
            policy=policy,
            job_id="invented-readable",
            publication_epoch="paused-invented",
            created_at=NOW,
            useful_until="2026-09-10T12:00:00Z",
            minimum_window_seconds=3600,
        )


@pytest.mark.parametrize("accepted", [False, True])
def test_actual_sdk_http_archive_and_rejection_retain_the_exact_whole_wire(
    journey_env, tmp_path, accepted
):
    from src.two_bot.request_archive_replay import load_archive, lineage

    bundle = source()
    script = dict(
        writer=[dict(text=writer_json(COPY))],
        safety=[dict(text="NO")],
        fact_check=[
            dict(
                text=fact_json(
                    accepted,
                    [{"text": COPY, "kind": "comparison"}],
                    failures=[] if accepted else ["Invented unsupported claim"],
                )
            )
        ],
    )
    if accepted:
        script["critic"] = [dict(text=critic_json("PASS"))]
    with freeze_time(NOW, tick=True):
        on = run_journey(
            script, root=private_root(tmp_path), bundle=bundle, state=deepcopy(DEFAULT_STATE)
        )
    archive = load_archive(on.archive)
    expected = capture_bundle(prepare_bundle(bundle)).payload()
    saved = json.loads(archive.artifact(archive.inputs[0]["bundle_artifact"]))
    assert saved == expected
    assert bool(on.draft) is accepted
    assert archive.status == "complete"
    [generation] = lineage(archive)
    assert generation["bundle_sha256"] == revisions.fingerprint(saved)
    for call in archive.calls:
        if call.stage != "safety":
            assert list(
                _request_bundles(json.loads(archive.artifact(call.logical_request.artifact)))
            ) == [saved]
    if not accepted:
        packet = on.out["rejected_candidate"]
        assert packet["bundle"] == saved and packet["bundle_sha256"] == revisions.fingerprint(saved)
        assert packet["verdict"]["passed"] is False and packet["verdict"]["response_diagnostic"]
        assert on.out["model_diagnostics"]  # Raw response is separate, never a fabricated verdict.


@pytest.mark.parametrize(
    "key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar_date")]
)
@pytest.mark.parametrize("layout", ["paired", "single", "asymmetric", "empty"])
def test_complete_calendar_layout_roundtrips_without_inventing_absent_observations(
    paired_variants, key, layout
):
    # Layout integrity only: modified fixture revision hashes are deliberately
    # not recomputed or presented as independently qualified scientific input.
    full = deepcopy(paired_variants[key]["review_context"]["two_bot"]["bundle"])
    baseline = full["raw_signal_dump"]["evidence"]["baseline"]
    if layout == "single":
        element = "TMAX" if key[0] == "high" else "TMIN"
        full["raw_signal_dump"]["evidence"]["variables"].pop(
            "TMIN" if element == "TMAX" else "TMAX"
        )
        other = "temperature_2m_min" if element == "TMAX" else "temperature_2m_max"
        baseline["variables"][other].pop("candidate_accepted", None)
    if layout in ("asymmetric", "empty"):
        scope = baseline["variables"]["temperature_2m_min"]
        for mapping in (
            scope["calendar_years"],
            scope["calendar_samples"],
            scope["record_dates"]["calendar"],
            scope["record_values_c"]["calendar"],
        ):
            for day in list(mapping):
                if layout == "empty" or day.endswith("-01"):
                    del mapping[day]
    full["historical_context"]["baseline"] = deepcopy(baseline)
    wire = encode_full(full)
    assert json.dumps(decode_wire(wire), sort_keys=True, separators=(",", ":")) == json.dumps(
        full, sort_keys=True, separators=(",", ":")
    )
