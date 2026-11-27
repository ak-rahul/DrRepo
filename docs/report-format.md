# Report format

Every exporter and interface consumes one dict shape, `Report.to_dict()`.

```jsonc
{
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
      "investigation_depth": "deep",     // "shallow" | "deep"
      "investigation_trace": [{"tool", "tool_input", "observation"}],
      "notes": ["Deep investigation reached its 8-tool-call budget…"],
      "suppressed": [{"issue": Issue, "suppression": {…}}]   // excluded from this score
    }
  },
  "issues": [Issue, …],                  // all categories, most severe first (suppressed ones excluded)
  "suppressed": [{"issue": Issue, "suppression": {"rule", "path", "reason", "expires", "origin"}}],
  "quick_wins": ["…"],                   // up to 5 distinct low/medium recommendations
  "investigation_plan": {"security": {"depth": "deep", "rationale": "…"}},
  "collector_status": {"security": {"status": "ok", "detail": null}},
  "llm_usage": {"used_tokens", "max_tokens", "remaining_tokens"},      // when budget tracking is on
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
                               // license-audit, dependency_audit, readme_analyzer, repo_hygiene,
                               // investigator:<category>
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
| Documentation | README quality score (0–100) | — |

After a deep investigation, the investigator's *new* issues are applied on top of the deterministic score with the category's rescore scale (documentation 60, code quality 60, security 40, dependencies 40, maintainability 50).

**Overall score:** weighted mean over assessed categories (security 0.30, code quality 0.25, others 0.15), with the weights renormalized. A category is unassessed when its inputs were unavailable, for example a repo with no Python code for ruff, or OSV unreachable. **Grade:** A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F below.

## SARIF 2.1.0

- One `run` with driver `DrRepo`. Each distinct `source/rule_id` becomes a rule (e.g. `bandit/B602`, `osv.dev/GHSA-…`, `readme_analyzer`).
- Each issue produces one result per sampled location, with `uriBaseId: %SRCROOT%`. Issues without a location produce one result with no location.
- `level`: critical/high → `error`, medium → `warning`, low → `note`. Rules carry `security-severity` (9.5/7.5/5.0/2.0) so GitHub can rank security alerts.
