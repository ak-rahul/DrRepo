# 🩺 DrRepo

**Your Repository's Health Specialist**

Multi-agent AI platform that clones a public GitHub repository and runs a genuinely comprehensive
health check on it: real static analysis, security/secret scanning, dependency vulnerability
auditing, README quality, and maintainability signals — not just a README linter.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.58+-FF4B4B.svg)](https://streamlit.io)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

---

## What is DrRepo?

Give DrRepo a GitHub URL. It clones the repository into a temporary, size- and time-limited
sandbox, runs **five parallel recon collectors** over it, then a **Lead Investigator agent**
decides, per repository, which of the five categories deserve a deep, tool-calling investigation
versus a quick pass — and synthesizes everything into one scored report:

- 🔍 **Code Quality** — [ruff](https://astral.sh/ruff) + [semgrep](https://semgrep.dev) static analysis
- 🔒 **Security** — [bandit](https://bandit.readthedocs.io) + secret/credential scanning
- 📦 **Dependency Health** — manifest files checked against [OSV.dev](https://osv.dev) for known CVEs
- 📄 **Documentation** — README completeness, structure, examples, visuals
- 🏗️ **Maintainability** — tests/CI/license presence, activity recency

**Safety invariant:** the cloned repository's code is never executed, installed, or built.
Every collector and every investigator tool only *reads* or *parses* source and manifest files —
no `pip install`, `npm install`, or build scripts are ever run, and nothing is ever written back
to the analyzed repository. This is what makes it safe to point at arbitrary public repositories,
even with an LLM choosing which files to look at.

---

## Genuinely agentic, not just LLM-narrated

Most "AI code review" tools hand an LLM a fixed bundle of facts and ask it to write a summary.
DrRepo's deep path is different: the LLM decides what to look at.

- **Lead Investigator** (`src/agents/planner.py`) looks at the recon summary and picks, per
  category, `shallow` or `deep` — with a one-sentence rationale. A repo with a clean dependency
  scan and messy code gets code-quality investigated deeply and dependencies waved through;
  a different repo gets the opposite treatment. This decision is made fresh per run, not hardcoded.
- **Investigator agents** (`src/agents/investigator.py`) get a bounded tool-calling loop —
  `read_file`, `search_code`, `run_scanner_on_path`, `query_osv`, `get_file_git_history` — and
  decide for themselves which tool to call, with what arguments, and when they have enough
  evidence to stop. This is a real think-act-observe loop, not a fixed sequence of calls.
- **Every deep category ships its own trace.** The report's `investigation_trace` records the
  actual tool calls and observations an investigator made, so a "How It Investigated This"
  panel in the Streamlit UI (and a matching section in the CLI output) lets you audit *why* it
  reached a verdict, not just read the verdict.
- Set `ENABLE_DEEP_INVESTIGATION=false` to force every category through the fast, deterministic
  shallow path instead — useful as a cost control or a way to reproduce fully deterministic
  output.

---

## Architecture

```
[5 parallel recon collectors] ──▶ Lead Investigator (plans depth per category)
                                          │
                    for each category ───┼───
                    │                          │
              depth = shallow             depth = deep
              (one LLM call over          (bounded tool-calling loop:
               recon data)                 read_file / search_code /
                                            run_scanner_on_path /
                                            get_file_git_history / query_osv,
                                            until it decides it has enough)
                    │                          │
                    └────────────┬─────────────┘
                                 ▼
                            synthesizer ──▶ Report
```

Collectors are deterministic, non-LLM functions — they never do their own text parsing beyond
what's necessary to normalize tool output, so their behavior is fully unit-testable without
mocking an LLM. The shallow path consumes collector output and produces a narrative + prioritized
issues per category, same as before; the deep path additionally lets an investigator agent pull
its own evidence via tools before answering. A synthesizer merges all five categories into one
weighted overall score, carrying each category's `investigation_depth` and `investigation_trace`
along with it. See [CLAUDE.md](CLAUDE.md) for the full module-by-module breakdown.

---

## Quick Start

### Prerequisites

- Python 3.11+
- `git` on PATH (required — collectors shell out to it to clone repositories)
- A free [Groq API key](https://console.groq.com) and a [GitHub token](https://github.com/settings/tokens)

### Installation

```
git clone https://github.com/ak-rahul/DrRepo.git
cd DrRepo
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/Mac
pip install -r requirements.txt
```

### Configuration

```
cp .env.example .env
```

Then fill in `GROQ_API_KEY` and `GH_TOKEN` (see `.env.example` for every option, including
per-collector timeouts and feature toggles for hosts where `ruff`/`semgrep`/`bandit` aren't
installed, and the agentic-investigation knobs `ENABLE_DEEP_INVESTIGATION`,
`MAX_TOOL_CALLS_PER_INVESTIGATOR`, `INVESTIGATOR_TIMEOUT_SECONDS`).

### Run

```
streamlit run app.py                                     # Web UI at localhost:8501
python -m src.main https://github.com/psf/requests        # CLI
python scripts/run_health_api.py                          # Health API on port 8000
```

---

## What Gets Analyzed

| Category | Tooling | Example issues surfaced |
|---|---|---|
| Code Quality | ruff, semgrep | Unused imports, anti-patterns, complexity smells |
| Security | bandit, secret scanner | Hardcoded credentials, unsafe subprocess/eval usage |
| Dependencies | OSV.dev, deps.dev | Known CVEs, plus a strong-copyleft dependency (e.g. GPL) in a permissively-licensed project |
| Documentation | Custom README analyzer | Missing sections, no code examples, no badges/images |
| Maintainability | GitHub API | No tests/CI/license, inactive repository |

Each collector degrades gracefully: if a tool isn't installed on the host, or a repository is
too large or an unsupported language, that collector reports `skipped` with a reason instead of
failing the whole analysis — the final report's `collector_status` field is always transparent
about what actually ran.

**License compatibility checking** cross-checks each dependency's license (looked up via
[deps.dev](https://deps.dev), one request per package since it has no batch endpoint) against
the repository's own license from GitHub. It only raises a flag for the one case it can judge
with real confidence — a strong-copyleft dependency (GPL/AGPL) in a permissively-licensed
project — and says so explicitly in the finding rather than pretending to give legal advice.
Set `ENABLE_LICENSE_AUDIT=false` to skip the extra lookups.

---

## Exporting Reports

Every analysis produces three files under `reports/`: `.json` (the full report), `.md` (a
human-readable summary), and `.sarif` (SARIF 2.1.0, for uploading to GitHub's code scanning /
Security tab, or any other SARIF-consuming tool). The Streamlit UI offers all three as download
buttons.

---

## Testing

```
pytest tests/ -v                        # all tests (coverage runs by default)
pytest tests/ -v -m "not integration"   # unit tests only -- hermetic, no env vars or network needed
pytest tests/ -v -m integration         # integration tests (real clone/network)
```

The unit suite is fully hermetic: every collector/agent takes its config or LLM client via
constructor injection, so `pytest -m "not integration"` passes with **zero** environment
variables set.

---

## Docker

```
docker build -t drrepo:latest .
docker run -p 8501:8501 --env-file .env drrepo:latest
```

or

```
docker-compose up
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE.md](LICENSE.md).

---

<div align="center">

**Made with ❤️ by [AK Rahul](https://github.com/ak-rahul)**

**DrRepo** | Your Repository's Health Specialist 🩺

</div>
