# Understanding DrRepo v2's Report

This document shows the actual shape of a DrRepo v2 report and which component produces each
part of it. Every field shown below is verifiable against `src/models.py` (`Report.to_dict()`).

## Pipeline

1. **Collectors** (deterministic, no LLM) gather raw facts: GitHub metadata, README structure,
   `ruff`/`semgrep` findings, `bandit`/secret-scan findings, and OSV.dev dependency vulnerability
   hits.
2. **Analyst agents** (LLM-based) turn each collector's findings into a narrative + a list of
   `Issue`s for one category. Severity, file, and line always come from the collector's own
   data — never from LLM-generated text — so a hallucinated file path can't end up in a report.
3. **Synthesizer** merges the five categories into one weighted `overall_score` and a single,
   severity-sorted issue list.

## Report shape

```json
{
  "repository": {
    "name": "requests",
    "url": "https://github.com/psf/requests",
    "language": "Python",
    "stars": 51234,
    "forks": 9123
  },
  "overall_score": 82.4,
  "category_scores": {
    "documentation": {"category": "documentation", "score": 90.0, "summary": "...", "issues": []},
    "code_quality": {"category": "code_quality", "score": 95.0, "summary": "...", "issues": [...]},
    "security": {"category": "security", "score": 100.0, "summary": "...", "issues": []},
    "dependencies": {"category": "dependencies", "score": 60.0, "summary": "...", "issues": [...]},
    "maintainability": {"category": "maintainability", "score": 100.0, "summary": "...", "issues": []}
  },
  "issues": [
    {
      "severity": "high",
      "category": "dependencies",
      "title": "requests@2.6.0: PYSEC-2018-28",
      "description": "Known vulnerability PYSEC-2018-28 affects requests 2.6.0.",
      "recommendation": "Upgrade requests past 2.6.0. Details: https://osv.dev/vulnerability/PYSEC-2018-28",
      "file": null,
      "line": null,
      "source": "osv.dev"
    }
  ],
  "quick_wins": ["Add a table of contents", "..."],
  "collector_status": {
    "repo_clone": {"status": "ok", "detail": null},
    "github_metadata": {"status": "ok", "detail": null},
    "readme": {"status": "ok", "detail": null},
    "static_analysis": {"status": "ok", "detail": null},
    "security": {"status": "ok", "detail": null},
    "dependency_audit": {"status": "ok", "detail": null}
  }
}
```

## Why `collector_status` matters

If `semgrep` or `bandit` isn't installed on the machine running DrRepo, or a repository is too
large to clone within the configured size limit, the corresponding collector reports
`"skipped"` with a human-readable `detail` instead of crashing the whole analysis. Always check
`collector_status` before treating a category's absence of issues as "clean" — it might mean
"not checked."

## Running it yourself

```
python -m src.main https://github.com/psf/requests
```

produces both a `.json` and a `.md` report under `reports/`. See `examples/basic_usage.py` for
the equivalent as a Python script.
