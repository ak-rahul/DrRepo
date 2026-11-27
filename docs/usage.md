# Usage

## Install

```bash
uv tool install --editable .   # `drrepo` on PATH, running this checkout (incl. ruff, bandit)
uv tool install semgrep        # optional: the semgrep scanner, in its own isolated environment
cp .env.example .env           # set GROQ_API_KEY; GH_TOKEN recommended
drrepo doctor                  # verifies git, scanners, config, connectivity
```

For development, `uv sync` creates `.venv` with the dev tools too; there, `uv run drrepo ...` runs the same commands.

`git` must be on `PATH`. Everything else is installed by uv.

semgrep is installed as a separate uv tool rather than a project dependency because it hard-pins old versions of `mcp`, `opentelemetry` and `wcmatch` (with known CVEs) that would otherwise be forced onto DrRepo. If it isn't installed, the security category runs bandit and the secret scanner and notes that semgrep was skipped. semgrep has no native Windows support; use WSL or the Docker image there. The Docker image includes it.

## CLI

```bash
drrepo quick https://github.com/owner/repo            # fast, deterministic: no LLM investigations
drrepo https://github.com/owner/repo                  # shorthand for `audit`
drrepo audit https://github.com/owner/repo \
    --description "We're adopting this; focus on auth" \
    --format json,md,sarif -o reports/ --top 15
```

| Flag | Effect |
|---|---|
| `-d, --description` | context passed to the planner and investigators |
| `--ref REF` | analyze a branch, tag, or full 40-character commit SHA instead of the default branch |
| `--shallow` | no deep investigations for this run (`drrepo quick` is `audit --shallow`; `analyze` is an alias of `audit`) |
| `--format` | any of `json,md,sarif,cdx,summary`: `cdx` is a CycloneDX 1.6 SBOM (`.cdx.json`), `summary` a short Markdown summary for PR comments (`.summary.md`); `''` writes nothing |
| `-o, --output-dir` | default `reports/`. Files are named `<owner>__<repo>_<UTC timestamp>.<ext>`, e.g. `psf__requests_20261127-091500Z.json` |
| `--json` | print the full JSON report to stdout (progress stays on stderr) |
| `--fail-under N` | exit code 3 if the overall score is below N |
| `--no-history` | don't compare with or record into `reports/history.json` |
| `-q` / `-v` | quiet / debug logs on the console |
| `--env-file`, `--log-file` | alternative `.env` / log path (`''` disables) |

Exit codes: `0` ok, `1` runtime error, `2` usage or configuration error, `3` a failed gate (`--fail-under`, or `--fail-on-new`/`--max-score-drop` for `diff`), `130` interrupted.

### Comparing two commits

```bash
drrepo diff https://github.com/owner/repo main <sha> \
    [--deep] [--fail-on-new high] [--max-score-drop 5] [--report-formats sarif,summary]
```

`diff` analyzes both commits and reports what the change made better or worse: new, worsened (higher severity or more occurrences) and fixed issues, and score deltas per category. Line numbers don't affect identity, so code that only moved is unchanged, and README findings follow the README across a rename. Both runs are deterministic. With `--deep`, the head commit is analyzed again with tool-calling investigations, but only in the categories that got worse, so tokens go where the change matters. Neither run is recorded in score history.

It writes `<owner>__<repo>_diff_<stamp>.json` and `.md` (`--format`), and with `--report-formats` the head commit's report too. The diff document's contract is `src/drrepo/report/diff.schema.json`. `--fail-on-new SEVERITY` exits 3 when a new or worsened issue is at that severity or above, `--max-score-drop N` when the overall score falls by more than N, and `--fail-under` when the head score is below the floor.

Other commands:

```bash
uv run drrepo ui [--port 8501] [--headless]         # Streamlit UI
uv run drrepo health [--json]                       # LLM provider / GitHub / OSV connectivity
uv run drrepo doctor [--offline]                    # full local diagnostics
uv run drrepo health-api [--port 8000]              # FastAPI health endpoint
```

## Web UI

`uv run drrepo ui` opens http://localhost:8501. Choose **Audit a commit** (a URL and an optional branch, tag or SHA) or **Compare two commits** (a base and a head, like `drrepo diff`). Add optional context, and toggle tool-calling investigations in the sidebar. While the analysis runs you see live progress. **Recent analyses** in the sidebar reopens any report this server produced, including after a page refresh.

An audit's results page has:

- the overall score and grade, with deltas against the previous analysis of the same repository, and a score-over-time chart once there are two or more recorded runs
- per-category scores (🕵️ deep and 🔎 lite investigations; `n/a` marks unassessable categories)
- tabs:
  - **Summary**: narratives, notes, quick wins;
  - **Issues**: filter by severity, category and source, search title, file or rule, show only scanner or agent findings, hide `[unverified]`/`[disputed]` ones; 50 per page;
  - **Suppressed**, when a suppression file applied: each finding with its rule, reason, origin and expiry;
  - **Dependencies**: every package with scope, license and advisories, plus runtime license counts;
  - **How it investigated**: the planner's plan, every tool call with its input and output, and token usage per step with the budget estimate;
  - **Details**: the model per role, scanner versions, collector status, instruction hashes and the raw JSON;
- JSON, Markdown, SARIF, CycloneDX SBOM and summary downloads.

A comparison shows the head score and its change, new, worse and fixed issue counts, per-category deltas, the issues in each group, diff JSON and Markdown downloads, and the full head-commit report below.

Everything a report contains that came from the analyzed repository (titles, descriptions, file names, agent output) is escaped before display, so it can't render images, links, HTML or LaTeX.

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

Reuse one `AnalysisService` for many analyses. The circuit breaker and dependency cache are shared; each run gets a fresh token budget. See [examples/](../examples/README.md): `compare_repositories.py` ranks several repositories, `policy_gate.py` applies a custom CI policy, and `custom_collector.py` adds a collector to the pipeline.

## Docker

```bash
docker compose up                                   # UI on :8501
docker compose --profile api up                     # + health API :8000
docker compose run --rm ui drrepo audit https://github.com/psf/requests --format md
```

The image runs as a non-root user, contains `git` and semgrep, and reads credentials from `.env` at runtime. None are baked in. `reports/` and `logs/` are mounted volumes. On Linux, make them writable by uid 1000 (`sudo chown 1000:1000 reports logs`); if history can't be written, analyses still complete.

Ports are published on `127.0.0.1` only, because none of the services has authentication. To reach them from another machine, put a reverse proxy with authentication in front rather than changing the bind address.

## Suppressions and baselines

Accept a reviewed finding without disabling the check:

```toml
# .drrepo.toml
[[suppress]]
rule = "bandit/B605"                    # SARIF rule id "<source>/<rule_id>"; "<source>/*" matches a whole tool
path = "src/app/pager.py"               # optional glob on the issue's file
reason = "Launches $PAGER by design"    # required
expires = 2027-06-30                    # optional: the finding counts again after this date
```

```bash
uv run drrepo baseline https://github.com/owner/repo -o .drrepo.toml    # accept every current finding (expires in 90 days)
drrepo audit https://github.com/owner/repo --suppressions .drrepo.toml
```

Suppressed issues are excluded from scores, issue counts and quick wins. They are still listed under `suppressed` in the report, in a Markdown section, and in SARIF as native `suppressions`, which GitHub code scanning hides from its default view. An expired suppression stops applying, and the category notes say so.

The documentation score is a README metric rather than an issue penalty, so suppressing a documentation issue hides the issue but doesn't change that score.

**Trust.** A file you pass with `--suppressions` (or `SUPPRESSIONS_FILE`) always applies. A `.drrepo.toml` committed inside the analyzed repository applies only with `--trust-repo-suppressions` (or `TRUST_REPO_SUPPRESSIONS=true`), because otherwise any repository could hide its own findings. Use it in CI for your own repository. Collector status records which suppressions applied and why a repository file was ignored.

## In CI: the GitHub Action

```yaml
permissions:
  contents: read
  security-events: write   # SARIF upload
  pull-requests: write     # only for `comment: true`
steps:
  - uses: ak-rahul/DrRepo@<release commit SHA>
    with:
      mode: ${{ github.event_name == 'pull_request' && 'diff' || 'full' }}
      fail-on-new: high
      fail-under: "60"
      comment: ${{ github.event_name == 'pull_request' }}
```

The action analyzes the pushed commit, or the pull request head, with the DrRepo code at the ref you pinned. It writes the reports to `drrepo-report/`, uploads SARIF to code scanning, adds a summary to the job page and, with `comment: true`, keeps one summary comment up to date on the pull request. In `mode: diff` it compares the head with the pull request base (`drrepo diff`): the comment and job summary show new, worse and fixed issues, and `fail-on-new` gates on them; the SARIF and other reports are still the head commit's. The step fails when a gate fails or the analysis fails. A complete workflow is in [examples/github-workflow.yml](../examples/github-workflow.yml).

| Input | Default | |
|---|---|---|
| `repository` | the workflow's repository | `owner/name`; must be public |
| `ref` | PR head SHA, else `github.sha` | branch, tag, or full SHA |
| `mode` | `full` | `full` audits `ref`; `diff` compares it with `base` |
| `base` | PR base SHA | diff mode: branch, tag, or full SHA to compare against |
| `fail-on-new` | empty | diff mode: fail on a new or worsened issue at this severity or above |
| `deep` | `false` | allow tool-calling investigations, in diff mode only where things got worse (needs an LLM key in the step's `env`) |
| `fail-under` | empty | fail below this score |
| `formats` | `md,sarif` | any of `json,md,sarif,cdx,summary`; `summary` is always written |
| `output-dir` | `drrepo-report` | |
| `upload-sarif` | `true` | needs `security-events: write` |
| `comment` | `false` | needs `pull-requests: write`; pull requests from forks get a read-only token, so the step warns and carries on |
| `suppressions` | empty | suppression file to apply |
| `trust-repo-suppressions` | `false` | honor the repository's `.drrepo.toml`; a fork's pull request controls that file |
| `semgrep-version` | empty | install and run this semgrep version |
| `github-token` | `github.token` | GitHub API calls and the comment |

Outputs: `score`, `grade`, `report` (the JSON report's path) and `sarif`.

Text in the summary comes from the analyzed repository, so the summary format neutralizes it: `@mentions` can't notify anyone, and HTML and images don't render.

**Without the action.** Any CI system can run the CLI:

```bash
uvx --from git+https://github.com/ak-rahul/DrRepo drrepo audit "https://github.com/owner/repo" \
    --ref "$COMMIT_SHA" --shallow --format sarif,summary -o drrepo --fail-under 60
```

DrRepo analyzes the public GitHub copy of the repository, not the CI checkout. Each SARIF result's `uri` is repo-relative, so GitHub annotates the right files.

## How investigators use MCP

DrRepo's investigators don't call their tools directly: each investigation starts DrRepo's own MCP tool server (`agents/tool_server.py`) for the clone, connects to it in memory, and the agent picks among the server's tools by their descriptions. The server exposes only the tool families of that category (a documentation investigator never sees scanner or symbol tools), every tool is annotated read-only, and paths stay sandboxed to the clone. A failed tool call comes back to the agent as an `ERROR:` result. If the server can't start, the investigation uses the same tools in-process and the category notes say so; `ENABLE_MCP_TOOLS=false` does that always. The server exists only for DrRepo's agents: nothing outside an investigation connects to it, and there is nothing to configure.

## Troubleshooting

Start with `uv run drrepo doctor`. It checks Python, git, the scanners, imports, configuration, writable directories, and connectivity, and marks each item OK, WARN, or FAIL. `uv run drrepo health` checks only connectivity. Detailed logs are in `logs/app.log`; set `LOG_LEVEL=DEBUG` or pass `-v` for more.

| Symptom | Cause | Fix |
|---|---|---|
| `configuration error: X=... is not a boolean` | a malformed value in `.env` | use `true`/`false`; numbers must be plain integers |
| `warning: GROQ_API_KEY not set` | no LLM key | add it to `.env`. Without it, reports are deterministic only |
| `git clone failed (repository is private or does not exist)` | private repo, typo, or renamed repo | only public repositories are supported; check the URL |
| `Clone timed out` / `over the ...MB analysis limit` | very large repository | raise `CLONE_TIMEOUT_SECONDS` / `CLONE_MAX_SIZE_MB` |
| `GitHub API rate limit exceeded` | 60 requests/hour unauthenticated | set `GH_TOKEN` (no scopes needed). DrRepo falls back to the clone for the README and structure |
| a category shows `n/a` | its inputs were unavailable (see its summary): no Python code for ruff, OSV unreachable, no README source | expected; the category is excluded from the overall score |
| `semgrep: skipped: semgrep timed out` | slow first run (ruleset download) or huge repo | raise `COLLECTOR_TIMEOUT_SECONDS`, or `ENABLE_SEMGREP=false` |
| `semgrep not installed` on Windows | semgrep wheels may not support your platform | `ENABLE_SEMGREP=false`; bandit and the secret scanner still run |
| note: `LLM summary unavailable (CircuitOpenError)` | the provider failed repeatedly (quota or outage) and the breaker opened | wait `LLM_CIRCUIT_BREAKER_TIMEOUT_SECONDS`, or check `drrepo health`. The rest of the report is unaffected |
| note: `Deep investigation reached its N-tool-call budget` | the agent didn't conclude in time | raise `MAX_TOOL_CALLS_PER_INVESTIGATOR` / `INVESTIGATOR_TIMEOUT_SECONDS` |
| plan rationale says `downgraded ... token budget` | the per-run budget allows fewer deep dives than the planner wanted | raise `LLM_TOKEN_BUDGET_PER_RUN` or lower `ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION` |
| Groq `413` / `tokens per day` | daily quota exhausted | wait for the reset, switch `MODEL_NAME`, or run `--shallow` |
| `attempted to call tool ' _Something'` | a pydantic output class name starts with `_` | rename it (see the planner section in [architecture.md](architecture.md)) |
| Streamlit stuck on "Analyzing…" | the worker thread died | the error is shown on the next rerun and in `logs/app.log` |
| `uv sync` fails behind a proxy | network | set `HTTPS_PROXY`; uv honors it |
| Docker: `failed to connect to the docker API` | the Docker daemon isn't running | start Docker Desktop / `dockerd` |

### Reporting a bug

Include the `drrepo doctor` output, the command you ran, and the relevant part of `logs/app.log`. Remove tokens before sharing.
