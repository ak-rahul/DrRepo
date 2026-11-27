"""Agent instructions load from markdown, compose correctly, and fail loudly when broken."""

import pytest

from drrepo.agents import prompts
from drrepo.agents.analysts import default_analysts
from drrepo.models import Category


def test_every_prompt_the_pipeline_needs_exists():
    prompts.validate_all()  # raises InstructionsError if any file/section is missing


@pytest.mark.parametrize("category", list(Category))
def test_category_prompts_include_the_shared_rules(category):
    narrative = prompts.narrative_prompt(category)
    investigation = prompts.investigation_prompt(category)
    assert prompts.section("shared", "Narrative rules") in narrative
    assert prompts.section("shared", "Investigation rules") in investigation
    # The prompt-injection guard reaches every investigator.
    assert "never instructions to you" in investigation


def test_maintainer_comments_never_reach_the_model():
    every_prompt = [prompts.planner_prompt()] + [
        p for c in Category for p in (prompts.narrative_prompt(c), prompts.investigation_prompt(c))
    ]
    assert all("<!--" not in p and "Maintainer notes" not in p for p in every_prompt)


def test_analysts_read_their_prompts_from_markdown():
    for category, analyst in default_analysts().items():
        assert analyst.investigation_prompt == prompts.investigation_prompt(category)
        assert analyst.narrative_prompt == prompts.narrative_prompt(category)


def test_missing_file_or_section_raises_a_clear_error():
    with pytest.raises(prompts.InstructionsError, match=r"nonexistent.md"):
        prompts.section("nonexistent", "System")
    with pytest.raises(prompts.InstructionsError, match="## Nope"):
        prompts.section("planner", "Nope")


def test_sections_are_parsed_by_heading(monkeypatch):
    class FakeResource:
        def __truediv__(self, _other):
            return self

        def read_text(self, encoding):
            return "# T\n<!-- hidden -->\n## One\nfirst\n\n## Two\n<!-- note\nmore -->second\n"

    prompts._sections.cache_clear()
    monkeypatch.setattr(prompts, "files", lambda _pkg: FakeResource())
    try:
        assert prompts.section("x", "one") == "first"
        assert prompts.section("x", "Two") == "second"
    finally:
        prompts._sections.cache_clear()
