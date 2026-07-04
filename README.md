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
sandbox and runs **five parallel collectors** and **five LLM analyst agents** over it, then
synthesizes everything into one scored report:

- 🔍 **Code Quality** — [ruff](https://astral.sh/ruff) + [semgrep](https://semgrep.dev) static analysis
- 🔒 **Security** — [bandit](https://bandit.readthedocs.io) + secret/credential scanning
- 📦 **Dependency Health** — manifest files checked against [OSV.dev](https://osv.dev) for known CVEs
- 📄 **Documentation** — README completeness, structure, examples, visuals
- 🏗️ **Maintainability** — tests/CI/license presence, activity recency

**Safety invariant:** the cloned repository's code is never executed, installed, or built.
Every collector only *parses* source and manifest files — no `pip install`, `npm install`, or
build scripts are ever run. This is what makes it safe to point at arbitrary public repositories.

---

## Architecture

```
                    ┌─ github_metadata ─┬─ readme
       clone repo ──┼─ static_analysis ─┤
    (outside graph) ├─ security ────────┼─→ [5 parallel analyst agents] ─→ synthesizer ─→ Report
                     └─ dependency_audit┘
```

Collectors are deterministic, non-LLM functions — they never do their own text parsing beyond
what's necessary to normalize tool output, so their behavior is fully unit-testable without
mocking an LLM. Analyst agents consume collector output and produce a narrative + prioritized
issues per category; a synthesizer merges the five categories into one weighted overall score.
See [CLAUDE.md](CLAUDE.md) for the full module-by-module breakdown.

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
installed).

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
| Dependencies | OSV.dev | Known CVEs in `requirements.txt`/`pyproject.toml`/`package.json` |
| Documentation | Custom README analyzer | Missing sections, no code examples, no badges/images |
| Maintainability | GitHub API | No tests/CI/license, inactive repository |

Each collector degrades gracefully: if a tool isn't installed on the host, or a repository is
too large or an unsupported language, that collector reports `skipped` with a reason instead of
failing the whole analysis — the final report's `collector_status` field is always transparent
about what actually ran.

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
