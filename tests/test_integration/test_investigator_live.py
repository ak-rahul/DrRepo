"""Integration test: a real tool-calling investigation against the live LLM.

Requires GROQ_API_KEY. Not part of the hermetic unit suite -- run explicitly
with `pytest -m integration`.

Known characteristic, not a bug: this talks to a real, non-zero-temperature
model, so it can occasionally answer without calling any tool at all even
when instructed to. Observed directly during development. The system prompt
below is written to minimize that, but if this test flakes on a re-run before
concluding there's a regression, re-run it once first.
"""

import pytest

from src.agents.base import build_llm_client
from src.agents.investigator import investigate
from src.config import Config
from src.models import Category
from src.tools.file_tools import make_file_tools


@pytest.mark.integration
class TestInvestigatorLive:
    def test_real_investigation_finds_hardcoded_secret(self, tmp_path):
        (tmp_path / "app.py").write_text(
            "import os\n"
            "\n"
            "AWS_SECRET_KEY = 'AKIAABCDEFGHIJKLMNOP'\n"
            "\n"
            "def connect():\n"
            "    return os.environ.get('DB_HOST')\n"
        )
        (tmp_path / "README.md").write_text("# Sample App\n\nA minimal sample app.\n")

        config = Config.from_env()
        missing = config.validate_for_llm()
        if missing:
            pytest.skip(f"Missing required config for live test: {missing}")

        llm_client = build_llm_client(config)
        tools = make_file_tools(str(tmp_path))

        result = investigate(
            category=Category.SECURITY,
            system_prompt=(
                "You are a security investigator. You MUST call read_file on app.py before "
                "answering -- do not respond without first reading it."
            ),
            tools=tools,
            llm_client=llm_client,
            recon_data={"language": "Python", "file_count": 2},
            max_tool_calls=config.max_tool_calls_per_investigator,
        )

        assert result["investigation_depth"] == "deep"
        read_file_calls = [t for t in result["investigation_trace"] if t["tool"] == "read_file"]
        assert read_file_calls, "investigator never called read_file"

        # This is the property that actually matters for correctness: the trace's
        # "observation" is real file content the model was given, not something it
        # invented. Whether the model then *judges* it worth flagging as an issue
        # (score, issues list) is model judgment, not something this test should pin --
        # that varies run to run against a live, non-zero-temperature model.
        assert any("AKIA" in call["observation"] for call in read_file_calls)
