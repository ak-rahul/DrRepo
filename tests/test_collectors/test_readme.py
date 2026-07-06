"""Tests for the README analyzer -- v1 had no coverage here at all, which is
how the broken image/link/badge regexes went unnoticed. These fixtures pin
down correct behavior."""

from src.collectors.readme import analyze_readme, generate_improvement_suggestions
from src.models import CollectorStatus


class TestAnalyzeReadme:
    def test_empty_content_returns_zeroed_analysis(self):
        result = analyze_readme("")

        assert result.status == CollectorStatus.OK
        assert result.data["word_count"] == 0
        assert result.data["quality_score"] == 0.0
        assert len(result.data["missing_sections"]) == 7
        # Must be title-cased the same way as the non-empty-content path
        # (`_find_missing_sections`) -- `docs_analyst._CRITICAL_SECTIONS`
        # compares against title-cased names, and a casing mismatch here
        # silently downgrades every missing-section issue to MEDIUM for a
        # repo with no README at all, instead of HIGH.
        assert "Installation" in result.data["missing_sections"]
        assert "installation" not in result.data["missing_sections"]

    def test_counts_images_links_and_badges_correctly(self, sample_readme_with_badges_and_images):
        result = analyze_readme(sample_readme_with_badges_and_images)
        data = result.data

        # 2 badges + 1 plain screenshot image = 3 images total
        assert data["image_count"] == 3
        # 2 badge-wrapping links + 2 TOC links + docs link + contributing link = 6
        assert data["link_count"] == 6
        assert data["badge_count"] == 2
        assert data["has_table_of_contents"] is True

    def test_image_without_shields_url_is_not_counted_as_badge(self):
        content = "![Screenshot](docs/screenshot.png)"
        result = analyze_readme(content)

        assert result.data["image_count"] == 1
        assert result.data["badge_count"] == 0

    def test_plain_link_not_double_counted_as_image(self):
        content = "Check out the [docs](https://example.com/docs) for more."
        result = analyze_readme(content)

        assert result.data["image_count"] == 0
        assert result.data["link_count"] == 1

    def test_missing_sections_detected(self):
        content = "# Project\n\nJust a title, nothing else."
        result = analyze_readme(content)

        assert "Installation" in result.data["missing_sections"]
        assert "License" in result.data["missing_sections"]

    def test_quality_score_rewards_completeness(self, sample_readme_with_badges_and_images):
        thin_result = analyze_readme("# Project\n\nOne line.")
        rich_result = analyze_readme(sample_readme_with_badges_and_images)

        assert rich_result.data["quality_score"] > thin_result.data["quality_score"]

    def test_quality_score_bounded_0_to_100(self, sample_readme_with_badges_and_images):
        score = analyze_readme(sample_readme_with_badges_and_images).data["quality_score"]
        assert 0.0 <= score <= 100.0

    def test_code_blocks_excluded_from_word_count(self):
        content = "Title\n\n```\nthis code should not count as words\n```\n\nreal words here"
        result = analyze_readme(content)

        assert result.data["word_count"] == 4  # "Title" + "real words here"


class TestGenerateImprovementSuggestions:
    def test_short_readme_suggests_expansion(self):
        suggestions = generate_improvement_suggestions({"word_count": 50})
        assert any("too short" in s["suggestion"].lower() for s in suggestions)

    def test_no_code_blocks_suggests_examples(self):
        suggestions = generate_improvement_suggestions({"code_block_count": 0, "word_count": 500})
        assert any("code examples" in s["suggestion"].lower() for s in suggestions)

    def test_complete_readme_yields_no_high_priority_suggestions(self):
        suggestions = generate_improvement_suggestions(
            {
                "word_count": 1000,
                "code_block_count": 5,
                "image_count": 2,
                "has_table_of_contents": True,
                "section_count": 10,
                "badge_count": 3,
            }
        )
        assert not any(s["priority"] == "high" for s in suggestions)
