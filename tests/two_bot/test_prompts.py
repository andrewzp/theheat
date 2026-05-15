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
