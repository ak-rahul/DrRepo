# Understanding DrRepo's Report

This document shows the actual shape of a DrRepo report and which component produces each part
of it. Every field shown below is verifiable against `src/models.py` (`Report.to_dict()`).

## Pipeline

1. **Recon collectors** (deterministic, no LLM) gather raw facts: GitHub metadata (including the
   repository's own SPDX license id), README structure, `ruff`/`semgrep` findings,
   `bandit`/secret-scan findings, OSV.dev dependency vulnerability hits, and each dependency's
   license from deps.dev.
2. **Lead Investigator** (`src/agents/planner.py`, one structured-output LLM call) looks at a
   compact recon summary and decides, per category, `"shallow"` or `"deep"` -- with a one-sentence
   rationale. This is a fresh decision every run, based on what recon actually found.
3. Each category then runs one of two paths:
   - **Shallow** (`src/agents/*_analyst.py`): one LLM call turns that category's collector output
     into a narrative + a list of `Issue`s. Severity, file, and line always come from the
     collector's own data -- never from LLM-generated text -- so a hallucinated file path can't
     end up in a report.
   - **Deep** (`src/agents/investigator.py`): a bounded tool-calling agent decides for itself
     which tools to call (`read_file`, `search_code`, `run_scanner_on_path`, `query_osv`,
     `get_file_git_history`) and in what order, until it has enough evidence, then emits the same
     `{summary, score, issues}` shape *plus* an `investigation_trace` of what it actually did.
4. **Synthesizer** merges the five categories into one weighted `overall_score` and a single,
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
    "documentation": {
      "category": "documentation",
      "score": 90.0,
      "summary": "...",
      "issues": [],
      "investigation_depth": "shallow",
      "investigation_trace": []
    },
    "code_quality": {
      "category": "code_quality",
      "score": 78.0,
      "summary": "Ruff flagged unused imports; a closer look at three files confirmed...",
      "issues": [
        {
          "severity": "low",
          "category": "code_quality",
          "title": "Unused import in utils/http.py",
          "description": "...",
          "recommendation": "...",
          "file": "utils/http.py",
          "line": 12,
          "source": "investigator:code_quality"
        }
      ],
      "investigation_depth": "deep",
      "investigation_trace": [
        {
          "tool": "run_scanner_on_path",
          "tool_input": {"tool": "ruff", "path": "utils/http.py"},
          "observation": "utils/http.py:12: F401 'os' imported but unused"
        },
        {
          "tool": "read_file",
          "tool_input": {"path": "utils/http.py"},
          "observation": "import os\nimport requests\n..."
        }
      ]
    },
    "security": {
      "category": "security",
      "score": 100.0,
      "summary": "...",
      "issues": [],
      "investigation_depth": "shallow",
      "investigation_trace": []
    },
    "dependencies": {
      "category": "dependencies",
      "score": 60.0,
      "summary": "...",
      "issues": ["..."],
      "investigation_depth": "shallow",
      "investigation_trace": []
    },
    "maintainability": {
      "category": "maintainability",
      "score": 100.0,
      "summary": "...",
      "issues": [],
      "investigation_depth": "shallow",
      "investigation_trace": []
    }
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
    },
    {
      "severity": "medium",
      "category": "dependencies",
      "title": "some-gpl-lib: GPL-3.0 dependency in a MIT-licensed project",
      "description": "some-gpl-lib@1.2.0 is licensed under GPL-3.0, a strong copyleft license, while this repository is licensed under MIT. Depending on how this dependency is used, this may create license compliance obligations for downstream users.",
      "recommendation": "Have this reviewed manually -- automated scanning can't determine whether some-gpl-lib is statically linked, dynamically linked, or invoked as a separate process, which changes the actual compliance risk.",
      "file": null,
      "line": null,
      "source": "license-audit"
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

(This example shows a mix of `shallow` and `deep` categories on purpose -- the Lead Investigator
sent `code_quality` deep because recon turned up ruff findings worth a closer look, and left the
other four categories shallow because their recon signal was already clean or unambiguous. Which
categories go deep varies per repository; nothing here is fixed.)

## Reading `investigation_depth` and `investigation_trace`

- `investigation_depth` is `"shallow"` for the fast, single-LLM-call path (v2's original
  behavior) and `"deep"` when the Lead Investigator routed that category to a tool-calling
  investigator.
- `investigation_trace` is only ever non-empty for `"deep"` categories. Each entry is one real
  tool call the investigator made -- `tool`, `tool_input`, and a truncated `observation` (what the
  tool actually returned). This is extracted from the agent's message history
  (`_extract_trace` in `src/agents/investigator.py`), not generated by the LLM itself, so it
  can't be a hallucinated account of "what it did."
- A `"deep"` category with a short or empty trace and a neutral score (~50) with a vague summary
  is the graceful-fallback path (the investigator hit its tool-call budget or the LLM call
  failed) -- see `docs/TROUBLESHOOTING.md`'s "Deep Investigation Issues" section, not a genuine
  clean result.
- Setting `ENABLE_DEEP_INVESTIGATION=false` forces every category to `"shallow"` and skips the
  Lead Investigator call entirely -- the report shape stays identical, just with every
  `investigation_trace` empty.

## License compatibility issues (`source: "license-audit"`)

`dependency_audit`'s collector data also carries a `licenses` list (one entry per package, with
a `license` field that's `None` when deps.dev couldn't determine it). The dependency analyst only
turns that into an issue in the one case it can judge with real confidence: the repository's own
license (from `github_metadata.license_spdx_id`) is permissive (MIT, Apache-2.0, BSD, ...) and a
dependency is strong copyleft (GPL, AGPL). Every other combination -- unknown repo license, weak
copyleft dependency, copyleft-licensed repo -- needs case-by-case legal judgment the heuristic
can't automate, so it stays silent rather than guessing. The issue's `recommendation` says this
explicitly; it's a heuristic pointer for manual review, not a legal determination.

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

produces a `.json`, `.md`, **and** `.sarif` report under `reports/` (the SARIF file is what you'd
upload to GitHub's code scanning / Security tab), and the CLI's own printed summary includes an
`[investigated]` tag and a "How it investigated" section for every deep category. See
`examples/basic_usage.py` for the equivalent as a Python script.
