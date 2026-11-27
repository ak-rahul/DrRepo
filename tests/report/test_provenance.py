"""Provenance: prompt hashes, model, and scanner versions recorded per report."""

from drrepo.agents import prompts
from drrepo.config import Config
from drrepo.evaluation import provenance_changes
from drrepo.report import provenance
from drrepo.report.provenance import INSTRUCTION_FILES, build_provenance, instruction_hashes


def test_every_instruction_file_is_hashed_stably():
    hashes = instruction_hashes()
    assert set(hashes) == set(INSTRUCTION_FILES)
    assert all(len(h) == 12 for h in hashes.values())
    assert instruction_hashes() == hashes


def test_hash_covers_sent_text_not_maintainer_comments(monkeypatch):
    texts = iter(
        [
            "## System\nDo X.\n<!-- note A -->",
            "## System\nDo X.\n<!-- note B -->",
            "## System\nDo Y.\n",
        ]
    )

    class Resource:
        def __truediv__(self, _other):
            return self

        def read_text(self, encoding):
            return next(texts)

    def digest():
        prompts._sections.cache_clear()
        provenance.instruction_hashes.cache_clear()
        monkeypatch.setattr(provenance, "INSTRUCTION_FILES", ("planner",))
        return provenance.instruction_hashes()["planner"]

    monkeypatch.setattr(prompts, "files", lambda _pkg: Resource())
    try:
        first, comment_edit, prompt_edit = digest(), digest(), digest()
    finally:
        prompts._sections.cache_clear()
        provenance.instruction_hashes.cache_clear()
    assert first == comment_edit != prompt_edit


def test_llm_is_null_without_a_model_and_tools_are_listed():
    record = build_provenance(Config(), llm_used=False)
    assert record["llm"] is None
    assert set(record["tools"]) == set(provenance.TOOLS)
    routed = Config(model_name="base", model_name_investigation="big")
    assert build_provenance(routed, llm_used=True)["llm"] == {
        "provider": "groq",
        "model": "base",
        "roles": {
            "planner": "base",
            "narrative": "base",
            "investigation": "big",
            "critic": "base",
        },
    }


def test_missing_tool_version_is_null(monkeypatch):
    provenance.tool_version.cache_clear()
    monkeypatch.setattr(provenance, "find_executable", lambda _t: None)
    try:
        assert provenance.tool_version("semgrep") is None
    finally:
        provenance.tool_version.cache_clear()


def test_eval_reports_what_changed():
    before = {"instructions": {"security": "a" * 12}, "llm": None, "tools": {"ruff": "0.17.6"}}
    after = {"instructions": {"security": "b" * 12}, "llm": None, "tools": {"ruff": "0.18.0"}}
    assert provenance_changes(before, after) == [
        "instructions changed: security",
        "ruff 0.17.6 -> 0.18.0",
    ]
    assert provenance_changes(before, before) == []
    assert provenance_changes(None, after) == []
