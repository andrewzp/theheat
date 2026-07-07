"""Structural assertions on the writer + fact-check prompts.

These tests guard the *shape* of the prompts after the 2026-05-15 fact-check
loosening — they don't exercise model behavior (voice-regression does that
against the live API). They catch:

- Accidental reversion of the WORLD_KNOWLEDGE allow-list to the old
  strict 95%+-confidence bar that was killing valid system clauses
  (Mozambique Channel, Isla del Coco, NOAA DHW alert-level semantics,
  IPCC AR6 framings).
- Removal of the narrow UNVERIFIABLE guards (named-facility specifics,
  snapshot-trend language, relative-position arithmetic).
- Loss of the editorial framing that says external knowledge is the
  product, not noise to strip away.
"""

from __future__ import annotations

from src.two_bot.prompts.critic_prompt import (
    CRITIC_SYSTEM_PROMPT,
    CRITIC_USER_PROMPT_TEMPLATE,
)
from src.two_bot.prompts.fact_check_prompt import FACT_CHECK_SYSTEM_PROMPT
from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT


class TestFactCheckPromptWorldKnowledgeAllowList:
    """The new fact-check prompt must keep its allow-list categories;
    losing one of these reopens the production failure mode where every
    coral_bleaching system clause was killed UNVERIFIABLE."""

    def test_keeps_world_knowledge_category(self):
        assert "WORLD_KNOWLEDGE" in FACT_CHECK_SYSTEM_PROMPT

    def test_drops_the_old_95_percent_confidence_bar(self):
        # The old bar pushed Gemini toward UNVERIFIABLE; the new framing
        # is qualitative ("established climate-science / oceanography").
        assert "95%+" not in FACT_CHECK_SYSTEM_PROMPT
        assert "95% confident" not in FACT_CHECK_SYSTEM_PROMPT

    def test_explicitly_allows_canonical_published_scales(self):
        # NOAA Coral Reef Watch DHW alert levels were the largest single
        # source of UNVERIFIABLE kills in the 2026-05-15 production audit.
        assert "Coral Reef Watch" in FACT_CHECK_SYSTEM_PROMPT
        assert "Bleaching Alert Level" in FACT_CHECK_SYSTEM_PROMPT
        assert "Saffir-Simpson" in FACT_CHECK_SYSTEM_PROMPT
        assert "Beaufort" in FACT_CHECK_SYSTEM_PROMPT

    def test_explicitly_allows_marine_geography(self):
        # The fact-checker was rejecting "Mozambique Channel sits between
        # Madagascar and the African coast" as UNVERIFIABLE. Allow-list
        # named features generally; spot-check Mozambique Channel.
        assert "Mozambique Channel" in FACT_CHECK_SYSTEM_PROMPT
        assert "Andaman" in FACT_CHECK_SYSTEM_PROMPT or "Coral Triangle" in FACT_CHECK_SYSTEM_PROMPT

    def test_explicitly_allows_ipcc_grade_climate_framings(self):
        assert "IPCC" in FACT_CHECK_SYSTEM_PROMPT
        # Basin-scale warming + ENSO mechanics were rejected as UNVERIFIABLE
        # for Arabian Sea and Eastern Tropical Pacific drafts respectively.
        assert "warming faster" in FACT_CHECK_SYSTEM_PROMPT
        assert "ENSO" in FACT_CHECK_SYSTEM_PROMPT or "El Niño" in FACT_CHECK_SYSTEM_PROMPT

    def test_frames_external_knowledge_as_editorial_product(self):
        # The opening reframe must survive — without it the model
        # defaults back to strict bundle-only matching.
        lowered = FACT_CHECK_SYSTEM_PROMPT.lower()
        assert "external knowledge" in lowered or "established climate" in lowered

    def test_says_accept_when_in_doubt(self):
        # The disposition matters: the default for borderline cases must
        # be acceptance, not rejection. Reversing this single phrase
        # would re-create the conservative-Gemini failure mode.
        assert "When in doubt, ACCEPT" in FACT_CHECK_SYSTEM_PROMPT


class TestFactCheckPromptNarrowGuardsRemain:
    """Loosening WORLD_KNOWLEDGE must not strip the targeted UNVERIFIABLE
    guards — those catch a different class of failure (the writer
    misreading the bundle data we already have)."""

    def test_facility_specifics_guard_kept(self):
        # Named-facility MW / capacity numbers must still be rejected
        # without bundle support (the Hoover Dam regression class).
        assert "Hoover Dam" in FACT_CHECK_SYSTEM_PROMPT
        assert "facilities" in FACT_CHECK_SYSTEM_PROMPT or "facility specifics" in FACT_CHECK_SYSTEM_PROMPT

    def test_snapshot_trend_guard_kept(self):
        assert "snapshot" in FACT_CHECK_SYSTEM_PROMPT.lower()
        # Specific banned trend phrases that surfaced in production:
        for phrase in ["still climbing", "approaching", "closing on"]:
            assert phrase in FACT_CHECK_SYSTEM_PROMPT

    def test_arithmetic_guard_kept(self):
        # The "halfway" / "midway" math-errors class — BUNDLE_FACT
        # failures observed for Gulf of Mannar and Kerala on 2026-05-15.
        assert "halfway" in FACT_CHECK_SYSTEM_PROMPT.lower()
        assert "midway" in FACT_CHECK_SYSTEM_PROMPT.lower()

    def test_comparative_superlative_guard_kept(self):
        # Reject ungrounded specifics like "warmest ocean water on Earth"
        # while still accepting the softer IPCC framing.
        assert "warmest ocean water on Earth" in FACT_CHECK_SYSTEM_PROMPT
        assert "superlative" in FACT_CHECK_SYSTEM_PROMPT.lower()

    def test_fabricated_archive_guard_kept(self):
        # "Largest April fire since 2012" style — archive specifics
        # without bundle support.
        assert "since 2012" in FACT_CHECK_SYSTEM_PROMPT or "archive" in FACT_CHECK_SYSTEM_PROMPT.lower()

    def test_archive_window_only_rule_kept(self):
        # archive_window_only is the existing constraint on
        # "all-time" / "ever" / "in recorded history" — must survive.
        assert "archive_window_only" in FACT_CHECK_SYSTEM_PROMPT
        assert "all-time" in FACT_CHECK_SYSTEM_PROMPT


class TestFactCheckPromptOutputContract:
    """The JSON output contract must remain unchanged — downstream parsing
    in src/two_bot/fact_check.py depends on it."""

    def test_output_shape_unchanged(self):
        # Single object, passed bool, failures array of {claim, category, reason}.
        assert '"passed": true | false' in FACT_CHECK_SYSTEM_PROMPT
        assert '"failures"' in FACT_CHECK_SYSTEM_PROMPT
        assert '"claim"' in FACT_CHECK_SYSTEM_PROMPT
        assert '"category"' in FACT_CHECK_SYSTEM_PROMPT
        assert '"reason"' in FACT_CHECK_SYSTEM_PROMPT

    def test_three_categories_unchanged(self):
        # BUNDLE_FACT / WORLD_KNOWLEDGE / UNVERIFIABLE — the three buckets
        # the parser expects.
        assert "BUNDLE_FACT" in FACT_CHECK_SYSTEM_PROMPT
        assert "WORLD_KNOWLEDGE" in FACT_CHECK_SYSTEM_PROMPT
        assert "UNVERIFIABLE" in FACT_CHECK_SYSTEM_PROMPT

    def test_no_markdown_directive_kept(self):
        assert "No markdown" in FACT_CHECK_SYSTEM_PROMPT


class TestWriterPromptSnapshotAndArithmeticGuards:
    """The writer-prompt nudges from the 2026-05-15 fact-check loosening:
    the writer should know when NOT to use trend language or
    relative-position math, since those aren't external-knowledge claims —
    they're misreadings of the bundle data we already have."""

    def test_snapshot_trend_bullet_present(self):
        assert "NO SNAPSHOT-TREND CLAIMS" in WRITER_SYSTEM_PROMPT
        for phrase in ["still climbing", "still accumulating", "closing on"]:
            assert phrase in WRITER_SYSTEM_PROMPT

    def test_snapshot_trend_bullet_lists_acceptable_trend_fields(self):
        # The writer needs to know WHEN trend language IS fair — the
        # rule isn't "never use direction language," it's "require a
        # bundle trend field." Spot-check named fields.
        assert "delta_kt_24h" in WRITER_SYSTEM_PROMPT
        assert "streak_days" in WRITER_SYSTEM_PROMPT or "monthly_delta_gt" in WRITER_SYSTEM_PROMPT

    def test_relative_position_arithmetic_bullet_present(self):
        assert "NO RELATIVE-POSITION CLAIMS THAT DON'T COMPUTE" in WRITER_SYSTEM_PROMPT
        for phrase in ["halfway", "midway"]:
            assert phrase in WRITER_SYSTEM_PROMPT


class TestWriterPromptKeepsLoosenedWorldKnowledgeFraming:
    """The writer-prompt section that mirrors the fact-check WORLD_KNOWLEDGE
    bar must drop the 95%+ wording and gain the established-science framing."""

    def test_drops_95_percent_wording(self):
        # The old "95%+ verifiable general knowledge" wording was
        # synced to the fact-check bar; it must move with the bar.
        assert "95%+ verifiable" not in WRITER_SYSTEM_PROMPT

    def test_names_the_authoritative_sources(self):
        # IPCC + NOAA + NASA + NSIDC + USGS — the bodies a climate-
        # literate reader would search to verify a claim.
        assert "NOAA" in WRITER_SYSTEM_PROMPT
        assert "IPCC" in WRITER_SYSTEM_PROMPT

    def test_calls_out_canonical_scales_as_fair_game(self):
        # NOAA Coral Reef Watch alert levels were specifically the
        # blocked-as-UNVERIFIABLE case driving the change.
        assert "Coral Reef Watch" in WRITER_SYSTEM_PROMPT
        assert "Saffir-Simpson" in WRITER_SYSTEM_PROMPT

    def test_frames_external_knowledge_as_editorial_product(self):
        # "editorial product" / "editorial value" — the disposition
        # that prevents future tightening from boiling everything
        # back to bundle-only quotation.
        lowered = WRITER_SYSTEM_PROMPT.lower()
        assert "editorial product" in lowered or "editorial value" in lowered


class TestWetBulbPromptGuardrails:
    def test_writer_labels_wet_bulb_as_forecast_model_output(self):
        assert "wet_bulb_extreme" in WRITER_SYSTEM_PROMPT
        assert "daily_max_tw_c" in WRITER_SYSTEM_PROMPT
        assert "forecast model" in WRITER_SYSTEM_PROMPT.lower()
        assert "survivability limit" in WRITER_SYSTEM_PROMPT

    def test_fact_checker_rejects_unsafe_wet_bulb_claims(self):
        assert "Wet-bulb physiology" in FACT_CHECK_SYSTEM_PROMPT
        assert "FORECAST MODEL" in FACT_CHECK_SYSTEM_PROMPT
        assert "survivability limit" in FACT_CHECK_SYSTEM_PROMPT
        assert "archive_max_tw_c" in FACT_CHECK_SYSTEM_PROMPT


class TestCriticPromptKillConditions:
    """Structural assertions on the critic prompt — the F3 second-pass
    editorial gate. These guard the kill conditions that justify the
    critic existing in the first place; if any of these disappear, the
    critic loses its main structural lift over the writer.
    """

    def test_default_to_kill_disposition(self):
        # The whole point of the critic is to be a HIGHER bar than the
        # writer self-imposes. "Default to KILL" sets that posture.
        assert "Default to KILL" in CRITIC_SYSTEM_PROMPT

    def test_two_gates_present(self):
        # Stop-mid-scroll + Send-it-to-a-friend — the @theheat
        # editorial bar mirrored from the writer prompt.
        assert "stop-mid-scroll" in CRITIC_SYSTEM_PROMPT.lower()
        assert "send-it-to-a-friend" in CRITIC_SYSTEM_PROMPT.lower()

    def test_template_convergence_is_the_signature_lift(self):
        # This is the structural reason the critic exists: it sees
        # cross-draft context (today's pending) that the writer cannot.
        assert "template_convergence" in CRITIC_SYSTEM_PROMPT.lower() or "template convergence" in CRITIC_SYSTEM_PROMPT.lower()
        # The motivating concrete example — 6 coral drafts same shape:
        assert "coral" in CRITIC_SYSTEM_PROMPT.lower()

    def test_recycled_phrasing_check(self):
        # The shipped library shrinks monotonically — same rule the
        # writer follows. Critic enforces by reading the recent shipped.
        assert "recycled" in CRITIC_SYSTEM_PROMPT.lower() or "shipped" in CRITIC_SYSTEM_PROMPT.lower()

    def test_dead_system_clause_check(self):
        # The "delete the system clause" test from the writer prompt —
        # critic catches the times the writer missed it.
        assert "system clause" in CRITIC_SYSTEM_PROMPT.lower()

    def test_voice_failures_mirrored(self):
        # The critic enforces the same voice rules the writer prompt
        # already lists. Spot-check the major ones.
        assert "hedging" in CRITIC_SYSTEM_PROMPT.lower()
        assert "wink" in CRITIC_SYSTEM_PROMPT.lower() or "wink-kicker" in CRITIC_SYSTEM_PROMPT.lower()
        assert "BREAKING" in CRITIC_SYSTEM_PROMPT or "breaking" in CRITIC_SYSTEM_PROMPT.lower()

    def test_bias_toward_kill_on_borderline(self):
        # Asymmetric cost rule — missed kill = boring tweet erodes
        # signal-to-noise; missed pass = good draft will return tomorrow.
        # Removing this would push the critic toward false-positive
        # PASSes and re-create the boring-feed failure mode.
        lowered = CRITIC_SYSTEM_PROMPT.lower()
        assert "bias toward kill" in lowered or "kill" in lowered

    def test_pass_conditions_present(self):
        # The critic must know what GOOD looks like, not just what BAD
        # looks like — otherwise it converges on always-KILL.
        assert "Pass conditions" in CRITIC_SYSTEM_PROMPT

    def test_period_of_record_length_is_not_a_kill_condition(self):
        """The critic was emitting kill reasons like "a 26-year period of
        record is too short to be an extraordinary climate signal" — wrong
        reasoning, since most weather-station histories are 25-50yr and the
        signal IS the record-vs-available-baseline. Andrew's 2026-06-01
        directive: "if super long records don't exist then the critic needs
        to assess relative to the data that exists." Lock that into the
        prompt as a regression test.
        """
        lowered = CRITIC_SYSTEM_PROMPT.lower()
        # Must explicitly call out that POR length is NOT a valid kill axis.
        assert "period-of-record length is not a kill condition" in lowered
        # Must include the "relative to data that exists" framing.
        assert "data that exists" in lowered
        # Must concretely cite the broken pattern so the model can't drift
        # back into it.
        assert "26-year" in CRITIC_SYSTEM_PROMPT or "26 years" in CRITIC_SYSTEM_PROMPT


class TestCriticPromptOutputContract:
    """JSON output contract — downstream parsing in src/two_bot/critic.py
    depends on this shape."""

    def test_output_shape_documented(self):
        assert '"verdict": "PASS" | "KILL" | "REVISE"' in CRITIC_SYSTEM_PROMPT
        assert '"kill_reason"' in CRITIC_SYSTEM_PROMPT
        assert '"revise_instruction"' in CRITIC_SYSTEM_PROMPT
        assert '"selected_index"' in CRITIC_SYSTEM_PROMPT

    def test_no_markdown_directive(self):
        assert "No markdown" in CRITIC_SYSTEM_PROMPT

    def test_kill_reason_examples_present(self):
        # Concrete examples — without these the model emits vague kill
        # reasons that the suppression dashboard can't render meaningfully.
        for example in ["template_convergence", "recycled_phrasing", "wink_kicker"]:
            assert example in CRITIC_SYSTEM_PROMPT


class TestFireBundleFourMoves:
    """E1 (plan row 8): the fire writer-prompt section — the reganom
    four-moves pattern generalized to the fire signal family. These guard
    the section's load-bearing phrases; losing one regresses fires to the
    data-ticker form ("A fire in X is radiating N MW, detected by satellite
    at N% confidence") that E1 exists to retire."""

    def test_fire_section_covers_both_signal_kinds(self):
        # One section, both fire signals: FIRMS/HMS hotspots (FRP snapshot)
        # and NIFC named-complex perimeter tier crossings.
        assert 'signal_kind = "fire" | "fire_footprint"' in WRITER_SYSTEM_PROMPT

    def test_move_one_lead_with_the_event_not_the_detection(self):
        # Satellite/confidence framing is attribution, not news.
        assert "Lead with the event, not the detection" in WRITER_SYSTEM_PROMPT

    def test_move_two_scale_words_over_raw_units(self):
        # frp_tier word anchors hotspots; footprints get the bundle's
        # pre-computed area equivalents so the writer never converts.
        assert "Scale words over raw units" in WRITER_SYSTEM_PROMPT
        assert "area_km2_approx" in WRITER_SYSTEM_PROMPT
        assert "area_acres_approx" in WRITER_SYSTEM_PROMPT

    def test_move_three_fire_names_are_bundle_or_nothing(self):
        # complex_name (or a human_impact entry naming the incident) is the
        # ONLY warrant for a fire name; hotspot bundles are nameless.
        assert "complex_name" in WRITER_SYSTEM_PROMPT
        lowered = WRITER_SYSTEM_PROMPT.lower()
        assert "nameless" in lowered

    def test_move_four_wires_the_a1_sourced_impact(self):
        # The A1 wiring: when human_impact rides the bundle, the human
        # stakes are usually THE story — and the rider's rules govern.
        assert "human_impact" in WRITER_SYSTEM_PROMPT
        assert "SOURCED HUMAN IMPACT" in WRITER_SYSTEM_PROMPT

    def test_operational_specifics_banned_by_name(self):
        # What the bundle cannot see, the writer cannot say.
        lowered = WRITER_SYSTEM_PROMPT.lower()
        assert "containment" in lowered
        assert "evacuation" in lowered

    def test_before_after_exemplar_present(self):
        # The reganom pattern: a ✗ ticker / ✓ story pair, same honest facts.
        assert "✗ ticker" in WRITER_SYSTEM_PROMPT
        assert "✓ story" in WRITER_SYSTEM_PROMPT


class TestFireExemplarTierConsistency:
    """Same lock as TestReganomRoundingExampleConsistency: prompt exemplars
    must agree with the bundle semantics they teach. A tier word that does
    not match _frp_tier for its exemplar MW teaches the writer a
    BUNDLE_FACT failure."""

    def test_very_high_exemplar_number_is_actually_very_high_tier(self):
        from src.two_bot.intern._shared import _frp_tier

        # The fire-section exemplar pairs 595 MW with the very_high tier.
        assert _frp_tier(595.0) == ("very_high", 500)
        assert "595 MW" in WRITER_SYSTEM_PROMPT
        assert "very-high-intensity" in WRITER_SYSTEM_PROMPT

    def test_existing_high_intensity_pairing_still_consistent(self):
        from src.two_bot.intern._shared import _frp_tier

        # The sentence-1 variety examples pair 309 MW with "high-intensity".
        assert _frp_tier(309.0) == ("high", 100)

    def test_area_examples_match_the_bundle_rounding(self):
        # codex r1 P1 regression lock: "about 1,030 km²" once taught altering
        # an exact-match bundle value. The move-2 examples must show the
        # DIGITS the intern produces for the documented case (103,400 ha).
        from src.two_bot.intern._shared import _round_sig

        assert round(103400 / 100.0) == 1034
        assert _round_sig(103400 * 2.47105) == 256000
        assert "about 1,034 km²" in WRITER_SYSTEM_PROMPT
        assert "about 256,000 acres" in WRITER_SYSTEM_PROMPT
        assert "1,030" not in WRITER_SYSTEM_PROMPT

    def test_approved_fire_exemplar_does_not_open_with_the_ticker(self):
        # codex r1 P1 regression lock: APPROVED EXEMPLARS #4 used to open
        # "A fire in Mali is radiating…" — the exact ticker shape the fire
        # section retires. An approved exemplar may never model the retired
        # opener.
        assert "A fire in Mali is radiating" not in WRITER_SYSTEM_PROMPT


class TestFireFactCheckPairing:
    """The E1 discipline: every fire-section loosening lands with a
    fact-check guard in the same PR. The writer teaches the move; the
    checker holds the leash."""

    def test_fire_rule_names_both_kinds(self):
        assert "fire_footprint" in FACT_CHECK_SYSTEM_PROMPT

    def test_fire_name_warrant_rule(self):
        # A proper fire name must trace to complex_name or a human_impact
        # entry's claim text; a recognized-from-training name is UNVERIFIABLE.
        assert "complex_name" in FACT_CHECK_SYSTEM_PROMPT
        assert "wrong fire" in FACT_CHECK_SYSTEM_PROMPT

    def test_hotspot_cannot_see_a_perimeter(self):
        # Acreage/perimeter figures on a `fire` hotspot bundle are
        # UNVERIFIABLE — a point detection has no perimeter.
        assert "cannot see a perimeter" in FACT_CHECK_SYSTEM_PROMPT

    def test_operational_specifics_guarded(self):
        lowered = FACT_CHECK_SYSTEM_PROMPT.lower()
        assert "containment" in lowered

    def test_area_approx_fields_accepted_with_marker(self):
        # The pre-rounded bundle areas are BUNDLE_FACT cited with "about" —
        # the marker is precision discipline, not hedging (reganom rule g
        # precedent).
        assert "area_km2_approx" in FACT_CHECK_SYSTEM_PROMPT
        assert "area_acres_approx" in FACT_CHECK_SYSTEM_PROMPT

    def test_tier_word_verified_as_bundle_fact(self):
        # "very-high-intensity" on a `high` bundle is a BUNDLE_FACT failure.
        assert "frp_tier" in FACT_CHECK_SYSTEM_PROMPT


class TestCriticUserPromptTemplate:
    """The user prompt template must accept the format keys the
    critic.py implementation passes. A mismatch (renamed key, missing
    key) causes KeyError at runtime — these tests catch it before
    deploy."""

    def test_template_accepts_all_required_keys(self):
        rendered = CRITIC_USER_PROMPT_TEMPLATE.format(
            draft_text="example",
            bundle_json="{}",
            pending_count=0,
            pending_drafts_block="(none)",
            shipped_count=0,
            shipped_tweets_block="(none)",
            revision_mode="REVISE unavailable",
        )
        assert "example" in rendered
        assert "(none)" in rendered

    def test_template_surfaces_draft_first(self):
        # Order matters for model attention — draft should be near the
        # top, bundle next, then comparison context.
        rendered = CRITIC_USER_PROMPT_TEMPLATE.format(
            draft_text="THE_DRAFT_MARKER",
            bundle_json='{"k": "THE_BUNDLE_MARKER"}',
            pending_count=0,
            pending_drafts_block="THE_PENDING_MARKER",
            shipped_count=0,
            shipped_tweets_block="THE_SHIPPED_MARKER",
            revision_mode="REVISE unavailable",
        )
        draft_pos = rendered.index("THE_DRAFT_MARKER")
        bundle_pos = rendered.index("THE_BUNDLE_MARKER")
        pending_pos = rendered.index("THE_PENDING_MARKER")
        shipped_pos = rendered.index("THE_SHIPPED_MARKER")
        assert draft_pos < bundle_pos < pending_pos < shipped_pos


class TestDetectionPlumbingBan:
    """P_tier (10 instances, 4 signal types, grade-capping at B in the
    grading corpus): internal detection taxonomy leaking into tweets.
    Observed actuals and bundle-designed anchors stay citable; the
    detector's own config never is."""

    def test_writer_bullet_present(self):
        assert "DETECTION PLUMBING IS NOT A FACT" in WRITER_SYSTEM_PROMPT
        assert "band_label" in WRITER_SYSTEM_PROMPT

    def test_observed_actuals_stay_sanctioned(self):
        assert "a fact about the storm" in WRITER_SYSTEM_PROMPT
        # Pre-existing sanctioned phrasing must SURVIVE this change:
        assert "above the 100 MW high-intensity threshold" in WRITER_SYSTEM_PROMPT

    def test_fact_check_pairing(self):
        assert "the bot's config is not a citable fact" in FACT_CHECK_SYSTEM_PROMPT.lower()
        assert "band_label" in FACT_CHECK_SYSTEM_PROMPT

    def test_critic_kill_condition(self):
        assert "internal_taxonomy_leak" in CRITIC_SYSTEM_PROMPT


class TestDustWhoAnchor:
    """P_dust (11/11 corpus instances): dust drafts carried no WHO-scale
    anchor. The anchor is the new co-measured PM10 bundle fact."""

    def test_dust_anchor_move_present_and_paired(self):
        assert "who_pm10_multiple" in WRITER_SYSTEM_PROMPT
        assert "who_pm10_multiple" in FACT_CHECK_SYSTEM_PROMPT
