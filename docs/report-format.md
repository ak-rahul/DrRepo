# Report format

Every exporter and interface consumes one dict shape, `Report.to_dict()`. Its contract is the JSON Schema [`src/drrepo/report/report.schema.json`](../src/drrepo/report/report.schema.json) (draft 2020-12). It ships in the package, so you can load it with `drrepo.report.schema.load_schema()`, and the MCP server serves it as `drrepo://schema/report`. The test suite validates every report shape the code can produce against it, and the schema rejects unknown fields, so the documentation can't drift from the output.

**Versioning.** `schema_version` is `MAJOR.MINOR`. A new optional field is a minor bump. A removed, renamed or retyped field is a major bump, and gets a changelog entry. Consumers should check the major version and ignore unknown optional fields.

```jsonc
{
  "schema_version": "1.0",
  "repository": {"name", "full_name", "url", "description", "language", "stars", "forks", "license",
                 "commit_sha",   // full SHA of the exact commit analyzed (null if the clone failed)
                 "ref"},         // requested branch/tag/SHA, else the default branch
  "overall_score": 73.7,                 // 0-100, weighted over assessed categories only
  "generated_at": "2026-11-27T12:35:46+00:00",
  "drrepo_version": "3.1.0",
  "issue_counts": {"critical": 0, "high": 2, "medium": 5, "low": 14},
  "category_scores": {
    "security": {
      "category": "security",
      "score": 68.7,
      "assessed": true,                  // false => excluded from overall_score, shown as n/a
      "summary": "…",                    // LLM narrative, or the deterministic summary
      "issues": [Issue, …],
      "investigation_depth": "deep",     // "shallow" | "lite" (half the tool calls) | "deep"
      "investigation_trace": [{"tool", "tool_input", "observation"}],
      "notes": ["Deep investigation reached its 8-tool-call budget…"],
      "suppressed": [{"issue": Issue, "suppression": {…}}]   // excluded from this score
    }
  },
  "issues": [Issue, …],                  // all categories, most severe first (suppressed ones excluded)
  "suppressed": [{"issue": Issue, "suppression": {"rule", "path", "reason", "expires", "origin"}}],
  "quick_wins": ["…"],                   // up to 5 distinct low/medium recommendations
  "dependencies": [{"ecosystem": "PyPI", "name": "jinja2", "version": "3.1.2",
                    "scope": "runtime",    // "runtime" | "dev"
                    "license": "BSD-3-Clause",          // deps.dev; null if unknown or not looked up
                    "vulnerabilities": ["GHSA-h5c8-…"]}], // OSV ids; the source of the SBOM
  "investigation_plan": {"security": {"depth": "deep", "rationale": "…"}},
  "collector_status": {"security": {"status": "ok", "detail": null}},
  "provenance": {                        // what produced this report
    "instructions": {"planner": "dbadf608dfea", "security": "…", …},  // hash of each prompt as sent
    "llm": {"provider": "groq", "model": "…"},                        // null when no LLM was used
    "tools": {"git": "2.47.0", "ruff": "0.17.6", "semgrep": null, …}  // null = not installed
  },
  "llm_usage": {"used_tokens", "max_tokens", "remaining_tokens",       // when budget tracking is on
                "by_label": {"planner": 900, "critic": 1200, "investigation:security": 9800, …},
                "deep_estimate": {"tokens": 11000, "source": "history"}},  // or "config"
  "score_history": {"previous_timestamp", "previous_commit_sha", "overall_score_delta",
                    "category_score_deltas"}  // when a previous run exists
}
```

**Issue**

```jsonc
{
  "severity": "high", "category": "security",
  "title": "bandit B602 (3 occurrences)",
  "description": "…", "recommendation": "…",
  "source": "bandit",          // collector/tool: ruff, bandit, semgrep, secret_scan, osv.dev,
                               // license-audit, license-policy, dependency_audit, readme_analyzer, doc_checks, repo_hygiene,
                               // investigator:<category>. Agent titles may start with
                               // "[unverified]" (grounding) or "[disputed]" (critic)
  "rule_id": "B602",           // tool-specific check id (null for some deterministic checks)
  "file": "app/run.py", "line": 12,       // first location (repo-relative)
  "locations": [{"file", "line"}],        // up to 20 samples
  "occurrences": 3
}
```

## Scoring

Severity weights: critical 25, high 10, medium 4, low 1. An aggregated issue costs `weight × (1 + log₂(occurrences))`, so repeated instances of one rule have diminishing impact. Penalties map onto a score with `score = 100 × e^(−penalty / scale)`, where a penalty equal to `scale` gives about 37.

| Category | Base | Scale |
|---|---|---|
| Security | 100 | 40 |
| Code quality | 100, penalty divided by thousands of Python lines (min 1) | 30 per kLOC (80 when size is unknown) |
| Dependencies | 100 | 40. Dev-only advisories are two severity levels lower; unrated advisories count as high |
| Maintainability | 100 | 50 |
| Documentation | README quality score (0–100), minus at most 15 for documentation checks (broken links, missing commands, low docstring coverage) | — |

After a deep investigation, the investigator's *new* issues are applied on top of the deterministic score with the category's rescore scale (documentation 60, code quality 60, security 40, dependencies 40, maintainability 50).

**Overall score:** weighted mean over assessed categories (security 0.30, code quality 0.25, others 0.15), with the weights renormalized. A category is unassessed when its inputs were unavailable, for example a repo with no Python code for ruff, or OSV unreachable. **Grade:** A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F below.

## SARIF 2.1.0

- One `run` with driver `DrRepo`. Each distinct `source/rule_id` becomes a rule (e.g. `bandit/B602`, `osv.dev/GHSA-…`, `readme_analyzer`).
- Each issue produces one result per sampled location, with `uriBaseId: %SRCROOT%`. Issues without a location produce one result with no location.
- `level`: critical/high → `error`, medium → `warning`, low → `note`. Rules carry `security-severity` (9.5/7.5/5.0/2.0) so GitHub can rank security alerts.

## Diff document

`drrepo diff` (and the MCP `compare_commits` tool) produce a separate document with its own contract, [`src/drrepo/report/diff.schema.json`](../src/drrepo/report/diff.schema.json), versioned by `diff_schema_version`. Its issues use the report's issue shape.

```jsonc
{
  "diff_schema_version": "1.0", "report_schema_version": "1.0",
  "repository": {"name", "full_name", "url"},
  "base": {"ref": "main", "commit_sha": "…", "overall_score": 81.0},
  "head": {"ref": "…", "commit_sha": "…", "overall_score": 76.5},
  "overall_delta": -4.5,
  "category_deltas": {"security": {"base": 86.0, "head": 73.6, "delta": -12.4}},  // null if unassessed
  "new_issues": [Issue, …],              // in head only, most severe first
  "fixed_issues": [Issue, …],            // in base only
  "worsened_issues": [{"issue": Issue, "base_severity": "medium", "base_occurrences": 1}],
  "unchanged_issues": 10,
  "deep_categories": ["security"],       // investigated with tools on the head (--deep)
  "generated_at": "…", "drrepo_version": "…"
}
```

**Identity.** Two issues are the same when category, source, rule id (the title for checks without a stable rule id, with `[unverified]`/`[disputed]` marks and occurrence counts removed) and file match; line numbers are ignored. README findings ignore the file, so renaming the README is not a fix.

## CycloneDX 1.6 SBOM

`--format cdx` writes `<name>.cdx.json`, built from `dependencies`: what the repository's manifests and lockfiles declare at the analyzed commit. Nothing is installed, so packages declared only as version ranges are absent (they are listed as `unpinned` in the dependency findings instead).

- One `library` component per package, with a [package URL](https://github.com/package-url/purl-spec) as `purl` and `bom-ref` (PyPI names normalized, npm scopes encoded). Ecosystems without a purl type get a plain `bom-ref` and no `purl`.
- `scope`: runtime → `required`, dev → `optional`.
- Licenses: an SPDX-shaped value is an `expression`, anything else a `name`.
- One `vulnerabilities` entry per OSV advisory, with `affects` pointing at the components. The advisory an issue is keyed on carries that issue's severity as a `DrRepo` rating, plus its recommendation.
- `metadata.component` is the repository, with the commit SHA as its version. `serialNumber` is derived from the repository URL and commit, so the same commit yields the same serial number.

The output validates against the official CycloneDX 1.6 JSON schema in the test suite.
