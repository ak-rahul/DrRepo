"""Deterministic analyst behavior: issues, scores, unassessed handling, LLM fallback."""

from unittest.mock import MagicMock

import pytest

from drrepo.agents.analysts import default_analysts
from drrepo.agents.analysts.base import aggregate, decay_score, issue_penalty, merge_issues
from drrepo.agents.analysts.code_quality import CodeQualityAnalyst, ruff_severity
from drrepo.agents.analysts.dependencies import (
    DependencyAnalyst,
    license_issues,
    license_policy_issues,
    vulnerability_issues,
)
from drrepo.agents.analysts.documentation import DocumentationAnalyst
from drrepo.agents.analysts.maintainability import MaintainabilityAnalyst, days_since
from drrepo.agents.analysts.security import SecurityAnalyst, dedupe_cross_tool, security_severity
from drrepo.agents.llm import LLMRuntime
from drrepo.errors import CircuitOpenError
from drrepo.models import Category, Issue, Location, Severity
from tests.conftest import failed, ok, skipped


def _issue(sev=Severity.LOW, title="t", file=None, occurrences=1):
    return Issue(
        sev,
        Category.SECURITY,
        title,
        "",
        "",
        "x",
        locations=[Location(file)] if file else [],
        occurrences=occurrences,
    )


class TestScoringPrimitives:
    def test_penalty_has_diminishing_returns(self):
        one = issue_penalty([_issue(Severity.HIGH)])
        many = issue_penalty([_issue(Severity.HIGH, occurrences=64)])
        assert one == 10 and many == 70  # 10 * (1 + log2(64))

    def test_decay_score(self):
        assert decay_score(0, 40) == 100
        assert decay_score(40, 40) == pytest.approx(36.8, abs=0.1)
        assert decay_score(10, 40, base=50) < 50

    def test_aggregate_groups_by_rule_and_samples_locations(self):
        findings = [
            {"tool": "ruff", "rule": "F401", "message": "unused", "file": f"f{i}.py", "line": i}
            for i in range(30)
        ]
        [issue] = aggregate(
            findings,
            category=Category.CODE_QUALITY,
            severity_of=lambda _f: Severity.LOW,
            title_of=lambda f, n: f"{f['rule']} x{n}",
            recommendation_of=lambda _f: "fix",
        )
        assert issue.occurrences == 30 and len(issue.locations) == 20
        assert "30 occurrences across 30 file(s)" in issue.description

    def test_merge_dedupes(self):
        base = [_issue(title="A", file="a.py")]
        merged = merge_issues(
            base, [_issue(title="a", file="a.py"), _issue(Severity.HIGH, title="B")]
        )
        assert [i.title for i in merged] == ["B", "A"]


class TestDocumentation:
    def test_unassessed_when_readme_missing(self):
        result = DocumentationAnalyst().assess({"readme": skipped()})
        assert result.assessed is False

    def test_license_section_downgraded_when_license_file_exists(self):
        recon = {
            "readme": ok(
                {
                    "word_count": 500,
                    "missing_sections": ["License", "Installation"],
                    "code_block_count": 2,
                    "quality_score": 70,
                }
            ),
            "repo_layout": ok(
                {"file_structure": {"has_license": True}, "readme_path": "README.rst"}
            ),
        }
        issues = {i.rule_id: i for i in DocumentationAnalyst().assess(recon).issues}
        assert issues["missing-section-license"].severity == Severity.LOW
        assert issues["missing-section-installation"].severity == Severity.HIGH
        assert issues["missing-section-installation"].file == "README.rst"

    def test_no_readme(self):
        result = DocumentationAnalyst().assess(
            {"readme": ok({"word_count": 0, "quality_score": 0})}
        )
        assert [i.rule_id for i in result.issues] == ["missing-readme"]
        assert result.narrative_facts is None  # nothing for the LLM to narrate


class TestCodeQuality:
    @pytest.mark.parametrize(
        ("rule", "sev"),
        [
            ("F821", Severity.HIGH),
            ("E999", Severity.HIGH),
            ("B006", Severity.MEDIUM),
            ("F401", Severity.LOW),
        ],
    )
    def test_ruff_severity(self, rule, sev):
        assert ruff_severity({"rule": rule}) == sev

    def test_density_normalized_by_python_lines(self):
        findings = [
            {"tool": "ruff", "rule": "F401", "message": "unused", "file": "a.py", "line": i}
            for i in range(10)
        ]
        small = CodeQualityAnalyst().assess(
            {
                "static_analysis": ok({"findings": findings}),
                "repo_layout": ok({"python_lines": 1000}),
            }
        )
        big = CodeQualityAnalyst().assess(
            {
                "static_analysis": ok({"findings": findings}),
                "repo_layout": ok({"python_lines": 50000}),
            }
        )
        assert big.score > small.score

    def test_non_python_repo_unassessed(self):
        recon = {
            "static_analysis": ok({"findings": []}),
            "repo_layout": ok({"python_lines": 0, "lines_by_language": {"Go": 900}}),
        }
        result = CodeQualityAnalyst().assess(recon)
        assert result.assessed is False and "Go" in result.summary

    def test_clean_repo(self):
        result = CodeQualityAnalyst().assess(
            {"static_analysis": ok({"findings": []}), "repo_layout": ok({"python_lines": 10})}
        )
        assert result.score == 100 and result.narrative_facts is None


class TestSecurity:
    def test_low_confidence_bandit_downgraded(self):
        assert (
            security_severity({"tool": "bandit", "severity": "HIGH", "confidence": "LOW"})
            == Severity.MEDIUM
        )
        assert (
            security_severity({"tool": "secret_scan", "severity": "CRITICAL"}) == Severity.CRITICAL
        )

    def test_cross_tool_dedupe(self):
        findings = [
            {"tool": "bandit", "file": "a.py", "line": 3},
            {"tool": "semgrep", "file": "a.py", "line": 3},
            {"tool": "semgrep", "file": "a.py", "line": 9},
        ]
        assert [f["line"] for f in dedupe_cross_tool(findings) if f["tool"] == "semgrep"] == [9]

    def test_secret_recommendation_and_score(self):
        recon = {
            "security": ok(
                {
                    "findings": [
                        {
                            "tool": "secret_scan",
                            "rule": "AWS Access Key",
                            "severity": "CRITICAL",
                            "file": "c.py",
                            "line": 1,
                        }
                    ],
                    "tool_status": {"secret_scan": "ok", "bandit": "skipped: x"},
                }
            )
        }
        result = SecurityAnalyst().assess(recon)
        assert result.issues[0].severity == Severity.CRITICAL
        assert "rotate" in result.issues[0].recommendation
        assert result.score < 60 and result.notes == ["bandit: skipped: x"]


class TestDependencies:
    def test_vulns_grouped_per_package_with_worst_severity_and_fix(self):
        vulns = [
            {
                "package": "req",
                "ecosystem": "PyPI",
                "version": "1.0",
                "vuln_id": "A",
                "severity": "low",
                "fixed_versions": ["1.2.0"],
            },
            {
                "package": "req",
                "ecosystem": "PyPI",
                "version": "1.0",
                "vuln_id": "B",
                "severity": None,
                "fixed_versions": ["1.10.0"],
            },
        ]
        [issue] = vulnerability_issues(vulns)
        assert issue.severity == Severity.HIGH  # unrated counts as high
        assert "1.10.0" in issue.recommendation  # numeric, not lexical, max

    def test_dev_only_vulns_downgraded(self):
        [issue] = vulnerability_issues(
            [
                {
                    "package": "pytest",
                    "ecosystem": "PyPI",
                    "version": "1",
                    "vuln_id": "A",
                    "severity": "critical",
                    "dev": True,
                }
            ]
        )
        assert issue.severity == Severity.MEDIUM and issue.title.endswith("(dev)")

    def test_license_conflict_only_for_permissive_repos(self):
        licenses = [{"package": "gpl-lib", "version": "1", "license": "GPL-3.0-only"}] + [
            {"package": f"u{i}", "version": "1", "license": None} for i in range(3)
        ]
        assert {i.rule_id for i in license_issues(licenses, "MIT")} == {
            "copyleft-in-permissive",
            "unknown-license",
        }
        assert license_issues(licenses, "GPL-3.0") == []

    def test_unpinned_without_lockfile(self):
        recon = {
            "dependency_audit": ok(
                {"packages_checked": 0, "unpinned": ["flask"], "manifests": ["requirements.txt"]}
            )
        }
        result = DependencyAnalyst().assess(recon)
        assert [i.rule_id for i in result.issues] == ["unpinned-dependencies"]
        assert result.issues[0].severity == Severity.MEDIUM

    def test_no_manifests_scores_full(self):
        result = DependencyAnalyst().assess(
            {"dependency_audit": ok({"packages_checked": 0, "manifests": []})}
        )
        assert result.score == 100 and result.assessed

    def test_audit_failure_unassessed(self):
        result = DependencyAnalyst().assess({"dependency_audit": failed("OSV down")})
        assert result.assessed is False and "OSV down" in result.summary

    def test_license_policy_replaces_the_heuristic(self):
        licenses = [
            {"package": "gpl-lib", "ecosystem": "PyPI", "version": "1", "license": "GPL-3.0-only"},
            {"package": "mpl-lib", "ecosystem": "PyPI", "version": "1", "license": "MPL-2.0"},
            {"package": "mit-lib", "ecosystem": "PyPI", "version": "1", "license": "MIT"},
            {"package": "unknown", "ecosystem": "PyPI", "version": "1", "license": None},
        ]
        found = {
            i.title.split(":")[0]: i
            for i in license_policy_issues(licenses, deny=("gpl-3.0-only",), allow=("MIT",))
        }
        assert set(found) == {"gpl-lib", "mpl-lib"}  # unknown licenses are not policy violations
        assert (found["gpl-lib"].rule_id, found["gpl-lib"].severity) == (
            "license-denied",
            Severity.HIGH,
        )
        assert (found["mpl-lib"].rule_id, found["mpl-lib"].severity) == (
            "license-not-allowed",
            Severity.MEDIUM,
        )
        assert {i.source for i in found.values()} == {"license-policy"}
        # Deny only: everything not denied passes.
        assert [i.rule_id for i in license_policy_issues(licenses, ("MPL-2.0",), ())] == [
            "license-denied"
        ]

    def test_policy_travels_in_the_collector_data(self):
        audit = {
            "packages_checked": 1,
            "manifests": ["requirements.txt"],
            "licenses": [
                {"package": "gpl-lib", "ecosystem": "PyPI", "version": "1", "license": "GPL-3.0"}
            ],
        }
        heuristic = DependencyAnalyst().assess({"dependency_audit": ok(audit)})
        assert [i.rule_id for i in heuristic.issues] == []  # no repo license: no conflict
        policy = {**audit, "license_policy": {"deny": ["GPL-3.0"], "allow": []}}
        enforced = DependencyAnalyst().assess({"dependency_audit": ok(policy)})
        assert [i.rule_id for i in enforced.issues] == ["license-denied"]

    @pytest.mark.parametrize(
        ("imported_in", "expected"),
        [
            (3, "Imported directly in 3 source file(s)."),
            (0, "likely a transitive dependency, still reachable"),
            (None, None),
        ],
    )
    def test_import_evidence_annotates_without_changing_severity(self, imported_in, expected):
        vuln = {
            "package": "req",
            "ecosystem": "PyPI",
            "version": "1.0",
            "vuln_id": "A",
            "severity": "high",
            "imported_in": imported_in,
        }
        [issue] = vulnerability_issues([vuln])
        assert issue.severity == Severity.HIGH
        if expected is None:
            assert "mported" not in issue.description
        else:
            assert expected in issue.description


class TestMaintainability:
    def test_layout_preferred_and_signals(self, github_data):
        github_data.update(stars=1000, archived=True, license_spdx_id=None)
        recon = {
            "github_metadata": ok(github_data),
            "repo_layout": ok(
                {"file_structure": {"has_tests": False, "has_ci": False}, "source_file_count": 5}
            ),
        }
        rules = {i.rule_id for i in MaintainabilityAnalyst().assess(recon).issues}
        assert {
            "archived",
            "no-tests",
            "no-ci",
            "no-license",
            "no-contributing",
            "no-changelog",
            "no-security-policy",
        } <= rules

    def test_falls_back_to_github_structure(self, github_data):
        result = MaintainabilityAnalyst().assess(
            {"github_metadata": ok(github_data), "repo_layout": skipped()}
        )
        assert result.assessed

    def test_unassessed_without_any_source(self):
        assert MaintainabilityAnalyst().assess({}).assessed is False

    def test_days_since(self):
        from datetime import UTC, datetime

        now = datetime(2026, 1, 11, tzinfo=UTC)
        assert days_since("2026-01-01T00:00:00Z", now) == 10
        assert days_since("garbage") is None and days_since(None) is None


class TestRunShallow:
    def test_llm_narrative_used(self, llm):
        recon = {
            "static_analysis": ok(
                {
                    "findings": [
                        {"tool": "ruff", "rule": "F401", "message": "m", "file": "a.py", "line": 1}
                    ]
                }
            )
        }
        finding = CodeQualityAnalyst().run_shallow(recon, llm)
        assert finding.summary == "A concise LLM narrative."

    def test_llm_failure_falls_back_with_note(self):
        broken = LLMRuntime(
            client=MagicMock(invoke=MagicMock(side_effect=CircuitOpenError("open")))
        )
        recon = {
            "static_analysis": ok(
                {
                    "findings": [
                        {"tool": "ruff", "rule": "F401", "message": "m", "file": "a.py", "line": 1}
                    ]
                }
            )
        }
        finding = CodeQualityAnalyst().run_shallow(recon, broken)
        assert finding.summary.startswith("ruff reported 1 findings")
        assert "CircuitOpenError" in finding.notes[0]

    def test_no_llm_configured(self):
        finding = SecurityAnalyst().run_shallow(
            {"security": ok({"findings": [], "tool_status": {}})}, LLMRuntime(client=None)
        )
        assert finding.score == 100


def test_registry_covers_every_category():
    assert set(default_analysts()) == set(Category)
    for analyst in default_analysts().values():
        assert analyst.investigation_prompt and analyst.narrative_prompt and analyst.tool_families


def test_ci_and_container_findings_have_bounded_impact_on_security():
    from drrepo.agents.analysts.security import INFRA_MAX_IMPACT, security_score
    from drrepo.models import Category, Issue, Severity

    def issue(source, severity, occurrences=1):
        return Issue(severity, Category.SECURITY, "t", "d", "r", source, occurrences=occurrences)

    # Even an enormous amount of workflow hygiene debt can't take more than INFRA_MAX_IMPACT.
    many = [issue("zizmor", Severity.HIGH, occurrences=500) for _ in range(20)]
    assert security_score(many) >= 100 * (1 - INFRA_MAX_IMPACT) - 0.1
    # The same findings from code scanners are not capped.
    assert security_score([issue("bandit", Severity.HIGH, occurrences=500)]) < 30
