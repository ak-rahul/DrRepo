# Usage

## Install

```bash
uv sync                  # creates .venv with locked dependencies (incl. ruff, bandit, semgrep)
cp .env.example .env     # set GROQ_API_KEY; GH_TOKEN recommended
uv run drrepo doctor     # verifies git, scanners, config, connectivity
```

`git` must be on `PATH`. Everything else is installed by uv.

## CLI

```bash
uv run drrepo https://github.com/owner/repo           # shorthand for `analyze`
uv run drrepo analyze https://github.com/owner/repo \
    --description "We're adopting this; focus on auth" \
    --format json,md,sarif -o reports/ --top 15
```

| Flag | Effect |
|---|---|
| `-d, --description` | context passed to the planner and investigators |
| `--shallow` | no deep investigations for this run |
| `--format` | any of `json,md,sarif`; `''` writes nothing |
| `-o, --output-dir` | default `reports/`. Files are named `<owner>__<repo>_<timestamp>.<ext>` |
| `--json` | print the full JSON report to stdout (progress stays on stderr) |
| `--fail-under N` | exit code 3 if the overall score is below N |
| `--no-history` | don't compare with or record into `reports/history.json` |
| `-q` / `-v` | quiet / debug logs on the console |
| `--env-file`, `--log-file` | alternative `.env` / log path (`''` disables) |

Exit codes: `0` ok, `1` runtime error, `2` usage or configuration error, `3` below `--fail-under`, `130` interrupted.

Other commands:

```bash
uv run drrepo ui [--port 8501] [--headless]         # Streamlit UI
uv run drrepo mcp [--transport stdio|sse|streamable-http]
uv run drrepo health [--json]                       # LLM provider / GitHub / OSV connectivity
uv run drrepo doctor [--offline]                    # full local diagnostics
uv run drrepo health-api [--port 8000]              # FastAPI health endpoint
```

## Web UI

`uv run drrepo ui` opens http://localhost:8501. Enter a URL and optional context, and toggle deep investigation in the sidebar. While the analysis runs you see live progress. The results page has:

- the overall score and grade, with deltas against the previous analysis of the same repository
- per-category scores (🕵️ marks deep-investigated categories; `n/a` marks unassessable ones)
- tabs: **Summary** (narratives, notes, quick wins), **Issues** (filter by severity and category), **How it investigated** (the planner's rationale and every tool call with its output), **Raw data** (collector status and full JSON)
- JSON, Markdown, and SARIF downloads

## Python

```python
from pathlib import Path

from drrepo.config import Config
from drrepo.service import AnalysisService, save_report

service = AnalysisService(Config.from_env())
report = service.analyze("https://github.com/psf/requests", deep=True, progress=print)
print(report["overall_score"], report["issue_counts"])
save_report(report, output_dir=Path("reports"), formats=("json", "sarif"))
```

Reuse one `AnalysisService` for many analyses. The circuit breaker and dependency cache are shared; each run gets a fresh token budget. See `examples/compare_repositories.py`.

## Docker

```bash
docker compose up                                   # UI on :8501
docker compose --profile api --profile mcp up       # + health API :8000, MCP :8765/mcp
docker compose run --rm ui drrepo analyze https://github.com/psf/requests --format md
```

The image runs as a non-root user, contains `git`, and reads credentials from `.env` at runtime. None are baked in. `reports/` and `logs/` are mounted volumes.

## In CI: gate and code scanning

```yaml
- uses: astral-sh/setup-uv@v6
- run: uvx --from git+https://github.com/ak-rahul/DrRepo drrepo analyze "https://github.com/${{ github.repository }}" --shallow --format sarif -o drrepo --fail-under 60
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: drrepo
```

DrRepo analyzes the public GitHub copy of the repository, not the CI checkout. Each SARIF result's `uri` is repo-relative, so GitHub annotates the right files.
