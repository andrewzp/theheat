from src.editorial.candidates import rank_candidates, score_candidate_text


class TestEditorialCandidates:
    def test_prefers_context_rich_candidate(self):
        bundle = rank_candidates(
            [
                "Phoenix is hot today.",
                "Phoenix just hit 121F. NEW RECORD. The old one was from 1998.",
            ],
            "record",
        )

        assert bundle.candidates[0].text == "Phoenix just hit 121F. NEW RECORD. The old one was from 1998."
        assert bundle.candidates[0].score.total > bundle.candidates[1].score.total

    def test_deduplicates_candidates_case_insensitive(self):
        bundle = rank_candidates(
            [
                "CO2 at Mauna Loa hit 434.0 ppm. Pre-industrial was 280.",
                "co2 at mauna loa hit 434.0 ppm. pre-industrial was 280.",
            ],
            "co2_milestone",
        )

        assert len(bundle.candidates) == 1

    def test_candidate_scoring_rewards_factual_structure(self):
        score = score_candidate_text(
            "Mauna Loa CO2: 434.1 ppm. First time above 434. Pre-industrial was 280.",
            "co2_milestone",
        )

        assert score.context >= 80
        assert score.total >= 75

    def test_category_hints_include_marine_heatwave(self):
        from src.editorial.candidates import CATEGORY_HINTS
        assert "marine_heatwave" in CATEGORY_HINTS
        hints = CATEGORY_HINTS["marine_heatwave"]
        assert "ocean" in hints
        assert "record" in hints
        assert "consecutive" in hints


class TestFireFootprintCategoryHint:
    def test_candidate_with_footprint_keywords_scores_higher(self):
        from src.editorial.candidates import score_candidate_text

        aligned = score_candidate_text(
            "The Dixie Complex has burned 213,000 hectares in California.",
            "fire_footprint",
        )
        generic = score_candidate_text(
            "A large fire is going on somewhere in California right now.",
            "fire_footprint",
        )
        assert aligned.context > generic.context
