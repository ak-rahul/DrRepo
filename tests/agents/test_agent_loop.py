"""The LLM paths end to end, with a scripted chat model instead of a provider.

Other tests mock `create_agent`. These run the real LangChain ReAct loop, the
real tools against a real (temporary) clone, real structured-output parsing,
and the real planner, so they catch integration breaks (renamed message
fields, a changed response-format strategy, tool-schema problems) that a mock
can't, without an API key or network.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from drrepo.agents.critic import CriticReviewOutput, CriticVerdictOutput
from drrepo.agents.investigator import InvestigationOutput, investigate
from drrepo.agents.llm import LLMRuntime, TokenBudget
from drrepo.agents.planner import CategoryPlanOutput, InvestigationPlanOutput
from drrepo.agents.rubric import DocumentationRubricOutput, RubricItem
from drrepo.agents.tools import build_tools
from drrepo.config import Config
from drrepo.models import Category, RepoRef
from drrepo.pipeline import RunContext, Workflow
from drrepo.report.schema import validate
from tests.conftest import ok

FINDING = {
    "summary": "Read app.py and confirmed a hardcoded debug flag in production code.",
    "issues": [
        {
            "severity": "medium",
            "title": "Debug mode enabled in production entry point",
            "description": "app.py sets DEBUG = True unconditionally.",
            "recommendation": "Read DEBUG from configuration and default it to False.",
            "file": "./app.py",
            "line": 1,
        }
    ],
}


class ScriptedChatModel(BaseChatModel):
    """Behaves like a tool-calling provider:

    - without tools bound: answers with a short narrative (shallow summaries);
    - with tools bound (the investigator): first calls `read_file`, then, once
      it has seen the tool result, submits `InvestigationOutput`;
    - `with_structured_output`: returns `plan` (planner), `rubric` (documentation)
      or `critique` (critic).

    `finding` replaces the investigator's submission (default: `FINDING`).
    """

    plan: Any = None
    rubric: Any = None
    critique: Any = None
    finding: Any = None
    tools_bound: bool = False

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **_kwargs: Any) -> Any:
        return self.model_copy(update={"tools_bound": True})

    def with_structured_output(self, schema: Any, **_kwargs: Any) -> Any:
        answers = {DocumentationRubricOutput: self.rubric, CriticReviewOutput: self.critique}
        answer = answers.get(schema, self.plan)
        return RunnableLambda(lambda _messages: answer)

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **_: Any
    ) -> ChatResult:
        if not self.tools_bound:
            message = AIMessage(content="Scripted narrative summary.")
        elif not any(isinstance(m, ToolMessage) for m in messages):
            message = AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "app.py"}, "id": "call-1"}],
            )
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": InvestigationOutput.__name__,
                        "args": self.finding or FINDING,
                        "id": "call-2",
                    }
                ],
            )
        message.usage_metadata = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
        return ChatResult(generations=[ChatGeneration(message=message)])


def _clone(tmp_path):
    root = tmp_path / "clone"
    root.mkdir()
    (root / "app.py").write_text("DEBUG = True\nprint('hello')\n", encoding="utf-8")
    return root


def test_real_react_loop_calls_tools_and_parses_findings(tmp_path):
    root = _clone(tmp_path)
    budget = TokenBudget(100_000)
    result = investigate(
        category=Category.SECURITY,
        system_prompt="Investigate security.",
        tools=build_tools(("files",), clone_root=str(root), config=Config(), cache=None),
        llm=LLMRuntime(client=ScriptedChatModel(), budget=budget),
        recon_data={"security": {"findings": []}},
        known_issues=[],
        max_tool_calls=4,
    )

    assert result.summary.startswith("Read app.py")
    [issue] = result.issues
    assert (issue.file, issue.line, issue.severity.value) == ("app.py", 1, "medium")
    assert issue.source == "investigator:security"
    # The trace holds the real tool call and its real observation (the file's content),
    # and leaves out the synthetic structured-output submission.
    [step] = result.trace
    assert step.tool == "read_file" and step.tool_input == {"path": "app.py"}
    assert "DEBUG = True" in step.observation
    assert budget.usage()["used_tokens"] > 0


def _patch_pipeline(tmp_path, monkeypatch) -> None:
    root = _clone(tmp_path)

    class Cloned:
        path = root

        def cleanup(self) -> None:
            pass

    monkeypatch.setattr("drrepo.pipeline.clone_repo", lambda *_a: (Cloned(), ok(name="repo_clone")))
    readme_layout = ok({"readme_content": "# Demo\n\nA tool.\n", "readme_path": "README.md"})
    monkeypatch.setattr("drrepo.pipeline.collect_repo_layout", lambda *_a, **_k: readme_layout)
    for name in (
        "collect_github_metadata",
        "collect_static_analysis",
        "collect_security",
        "collect_dependency_audit",
    ):
        monkeypatch.setattr(f"drrepo.pipeline.{name}", lambda *_a, **_k: ok({}))


def _plan(security_depth: str) -> InvestigationPlanOutput:
    return InvestigationPlanOutput(
        plans=[
            CategoryPlanOutput(
                category=c.value,
                depth=security_depth if c is Category.SECURITY else "shallow",
                rationale="scripted",
            )
            for c in Category
        ]
    )


def test_full_pipeline_with_planner_and_deep_investigation(tmp_path, monkeypatch):
    """Planner picks security as deep; that node runs the real agent loop on the clone."""
    _patch_pipeline(tmp_path, monkeypatch)
    plan = _plan("deep")
    rubric = DocumentationRubricOutput(
        items=[RubricItem(criterion="purpose", verdict="met", reason="states its purpose")]
    )
    ctx = RunContext(
        config=Config(groq_api_key="k"),
        llm=LLMRuntime(
            client=ScriptedChatModel(plan=plan, rubric=rubric), budget=TokenBudget(1_000_000)
        ),
    )
    report = Workflow().run(RepoRef("octo", "demo"), ctx)
    validate(report)  # deep reports (traces, agent issues) satisfy the schema too

    security = report["category_scores"]["security"]
    assert security["investigation_depth"] == "deep"
    assert [t["tool"] for t in security["investigation_trace"]] == ["read_file"]
    assert any(i["title"].startswith("Debug mode") for i in security["issues"])
    assert report["investigation_plan"]["security"]["depth"] == "deep"
    others = [c for name, c in report["category_scores"].items() if name != "security"]
    assert all(c["investigation_depth"] == "shallow" for c in others)
    assert report["llm_usage"]["used_tokens"] > 0
    # The documentation rubric ran through the real structured-output path.
    doc_notes = report["category_scores"]["documentation"]["notes"]
    assert any(n.startswith("Documentation rubric (1 met)") for n in doc_notes)


def test_lite_investigation_and_critic_through_the_pipeline(tmp_path, monkeypatch):
    """A lite investigation reports a high finding; the critic disputes it. The finding
    stays visible at low severity, and each LLM step has its own budget line."""
    _patch_pipeline(tmp_path, monkeypatch)
    severe = {
        **FINDING,
        "issues": [
            {**FINDING["issues"][0], "severity": "high", "title": "Debug flag exposes data"}
        ],
    }
    critique = CriticReviewOutput(
        verdicts=[
            CriticVerdictOutput(
                finding=1, verdict="reject", reason="line 1 is a constant in a demo script"
            )
        ]
    )
    ctx = RunContext(
        config=Config(groq_api_key="k", max_tool_calls_per_investigator=8),
        llm=LLMRuntime(
            client=ScriptedChatModel(plan=_plan("lite"), critique=critique, finding=severe),
            budget=TokenBudget(1_000_000),
        ),
    )
    report = Workflow().run(RepoRef("octo", "demo"), ctx)
    validate(report)

    security = report["category_scores"]["security"]
    assert security["investigation_depth"] == "lite"
    [disputed] = [i for i in security["issues"] if "Debug flag" in i["title"]]
    assert disputed["title"].startswith("[disputed] ")
    assert disputed["severity"] == "low"
    assert "Critic: line 1 is a constant" in disputed["description"]
    assert any(
        n.startswith("Critic reviewed 1 severe agent finding(s): 0 confirmed, 1 disputed")
        for n in security["notes"]
    )
    labels = report["llm_usage"]["by_label"]
    assert {"planner", "narrative", "investigation:security", "critic"} <= set(labels)
    assert report["llm_usage"]["deep_estimate"]["source"] == "config"
