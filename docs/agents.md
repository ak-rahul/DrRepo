# Agents

DrRepo's LLM-backed roles are one **Lead Investigator** that plans the audit, five **category analysts**, each of which can act on two paths, and a **critic** that re-checks severe agent findings. Every role's job description is a markdown file in [`src/drrepo/agents/instructions/`](../src/drrepo/agents/instructions/). These files are the prompts the models receive, so to change how an agent behaves, edit its document. You rarely need to touch Python.

What no agent does: decide scores. Scores and the file, line, rule and severity of every scanner finding come from deterministic code (`Analyst.assess()`). Agents write summaries, and on the deep path they add issues they verified with tools. Two exceptions are bounded: the [documentation rubric](#documentation-rubric) can move the documentation score by at most ±25 points, and the [critic](#critic) can lower (never raise) the severity of an agent's own severe findings. Without an API key, DrRepo runs with no agents at all and still produces a complete, deterministic report.

## How a run uses the agents

```
recon (no LLM) ─► Lead Investigator ─► for each of the 5 categories, in parallel:
                  (1 structured call)     assess() in code ─► Narrative (1 call)
                                          └─ if planned deep or lite: Investigation (ReAct loop with tools)
                                               ─► grounding (code) ─► critic (1 call, severe findings only)
```

Each role can use its own model (`MODEL_NAME_PLANNER`, `MODEL_NAME_NARRATIVE`, `MODEL_NAME_INVESTIGATION`, `MODEL_NAME_CRITIC`; see [configuration.md](configuration.md)). For example, use a small, fast model for summaries, your most reliable tool-user for investigations, and a different model family for the critic, so its second look is independent. The planner's model also runs the documentation rubric. All roles share the run's circuit breaker and token budget. The report's `provenance.llm.roles` records which model did what, and `llm_usage.by_label` how many tokens each step used.

| Role | Instructions | Calls per run | Output |
|---|---|---|---|
| Lead Investigator | `planner.md` → `## System` | 1 (skipped if deep investigation is off, there's no clone, or the budget is spent) | `InvestigationPlanOutput`: depth and rationale per category |
| Analyst, narrative path | `<category>.md` → `## Narrative`, plus `shared.md` → `## Narrative rules` | at most 1 per category, and only when there is something to narrate | a 3-5 sentence summary |
| Analyst, investigation path | `<category>.md` → `## Investigation`, plus `shared.md` → `## Investigation rules` | one bounded loop per category planned deep or lite | `InvestigationOutput`: summary and verified issues |
| Critic | `critic.md` → `## System` | at most 1 per investigated category, only if it reported a grounded high or critical finding | `CriticReviewOutput`: a verdict and reason per finding |

## Lead Investigator

**Job.** Decide which categories deserve a tool-calling investigation, and how much of one. The point is cost: investigations are slow and token-hungry, so they go only where the recon signals show risk or ambiguity. There are three depths:

| Depth | What runs | Budget units |
|---|---|---|
| `deep` | a full investigation (`MAX_TOOL_CALLS_PER_INVESTIGATOR` tool calls) | 2 |
| `lite` | the same investigation with half the tool calls, for borderline categories | 1 |
| `shallow` | the deterministic findings plus a narrative | 0 |

**Input (user message).** A compact recon summary from `pipeline.recon_summary`: finding counts by severity per scanner, vulnerable and unpinned dependency counts, README metrics, collector failures, the user's description if given, and the number of budget units this run can afford.

**How the budget is enforced.** Before the parallel fan-out, the planner node prices a unit at half of what one deep investigation is expected to cost, and computes how many units the run's remaining token budget covers. Whatever the model returns, `enforce_budget` keeps the plan within that, in the priority order security > dependencies > code quality > maintainability > documentation. A deep pick that doesn't fit becomes lite if one unit is left, otherwise shallow.

**Adaptive estimate.** The expected cost of a deep investigation comes from measurements when there are any. Each run records in the score history how many tokens its investigations really used (a lite one counts double), and the next run uses the mean of this repository's recent measurements, or of any repository's when this one has none. The estimate stays within a quarter and four times `ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION`, which is also the value used when nothing has been measured or history is off. `llm_usage.deep_estimate` in the report shows the value used and its source.

**Failure behaviour.** Any error (provider down, circuit open, malformed output) produces an all-shallow plan with the reason recorded. Planning never blocks an analysis.

## Category analysts

Each analyst lives in `agents/analysts/<category>.py` and has three parts:

1. `assess(recon)` is deterministic code. It turns collector output into `Issue`s and a 0–100 score, and prepares `narrative_facts`: a compact, prompt-ready view of the evidence.
2. **Narrative path (shallow):** one call with the `## Narrative` instructions and `narrative_facts` as the user message. If the call fails, the deterministic summary from `assess()` is used, with a note.
3. **Investigation path (deep):** a LangChain `create_agent` ReAct loop. It gets the `## Investigation` instructions, the trimmed recon data, the issues already found, and the analyst's tool families. New, deduplicated issues are merged into the recon findings and the analyst re-scores the union. The recon findings are never replaced.

| Category | Evidence `assess()` scores | Tool families on the deep path |
|---|---|---|
| security | bandit, semgrep `p/security-audit`, secret scanner, zizmor (workflows), hadolint and root-user check (Dockerfiles) | files, scanners, git_history |
| code_quality | ruff bug-class rules, normalized per 1k lines | files, scanners |
| dependencies | OSV.dev advisories (exact versions) with direct-import evidence, deps.dev licenses against the license policy, pinning | files, dependencies |
| documentation | README structure metrics | files |
| maintainability | tests, CI, license, policies, activity, archived status | files, git_history |

### Tools

All tools are read-only and treat every argument as hostile; see [architecture.md](architecture.md#security-model).

| Family | Tools | Notes |
|---|---|---|
| files | `read_file`, `list_directory`, `find_files`, `search_code` | Paths are sandboxed to the clone. `search_code` uses the `regex` engine with a per-line timeout and a total time budget, so a catastrophic-backtracking pattern can't hang a thread. |
| scanners | `run_scanner_on_path` | Re-runs ruff, bandit or semgrep on one path. Respects `ENABLE_BANDIT` and `ENABLE_SEMGREP`. |
| dependencies | `query_osv` | OSV.dev lookup for one exact version. Uses the shared lookup cache. |
| git_history | `get_file_git_history` | GitHub API, because the clone is shallow and has one commit. |

### Bounds on a deep investigation

| Bound | Setting | Default |
|---|---|---|
| Tool calls | `MAX_TOOL_CALLS_PER_INVESTIGATOR` (graph `recursion_limit = 2n + 4`) | 8 |
| Wall clock | `INVESTIGATOR_TIMEOUT_SECONDS` | 90 s |
| Prompt size | recon data trimmed by `summarize_recon_data` (long strings and lists capped) | — |
| Tokens | counted against the run's `TokenBudget` | 60,000 per run |
| Provider failures | the shared `CircuitBreaker` opens after `LLM_CIRCUIT_BREAKER_THRESHOLD` failures | 3 |

### Grounding check

Before an investigator's issues are merged, `agents/grounding.py` verifies each one against the clone and the investigator's own tool trace. No LLM is involved.

| Finding | Result |
|---|---|
| Cites a file that doesn't exist, a path outside the repository, or a line past the end of the file | **dropped**, and logged with the reason |
| Cites a real file the agent never read, searched or scanned (listing a directory doesn't count) | kept, **capped at `low`**, title prefixed `[unverified]` |
| Includes an `evidence` excerpt that isn't within 15 lines of the cited line | kept, capped at `low`, marked unverified |
| Cites no file at all | kept, capped at `low`, marked unverified |
| Everything else | unchanged |

The category's notes record how many findings were dropped or downgraded, so the effect is visible in every report. Agents are told these rules in `shared.md`.

### Critic

A high or critical agent finding moves scores, so it gets a second, independent look before it is merged (`agents/critic.py`, instructions in `critic.md`). After grounding, the grounded high and critical findings of one investigation (at most 6) go to the critic in one structured call, with no tools. It sees each claim and the cited code with line numbers, fenced as data, and answers per finding:

| Verdict | Applied in code |
|---|---|
| `confirmed` | unchanged |
| `downgrade` | one severity level lower, with the reason appended |
| `reject` | `low`, title prefixed `[disputed]`, reason appended; the finding stays in the report |
| no answer | unchanged |

The critic can never raise a severity, remove a finding, or touch a scanner finding, and a failed call changes nothing, so the worst a prompt injection in the analyzed code can achieve is a visible "disputed" agent finding. The category's notes record the verdict counts. `drrepo eval` measures the critic against human labels: how many disputed findings were labeled false positives, and how many labeled false positives it caught. Turn it off with `ENABLE_AGENT_CRITIC=false`.

Any failure raises `InvestigationError` inside the loop. The category then falls back to its shallow result, and the report notes why. The trace of every tool call (tool, input, truncated output) is kept in the report, so a reader can check that each claim came from real evidence.

## Documentation rubric

README metrics (headings, word counts) are DrRepo's weakest heuristic. When an LLM is available (and `ENABLE_LLM_JUDGMENT` is on), the documentation analyst's `judge()` makes one structured call (`agents/rubric.py`, instructions in `documentation.md` under `## Rubric`). It grades the README against six criteria: purpose, installation, usage, configuration, contributing and status. Each gets `met`, `partial`, `missing` or `not_applicable`, with a reason. The model also sees the project's real build config (package name, entry points, lockfiles from `repo_layout.build_config`), so it can check that install and usage instructions match reality. The README is fenced as data.

Everything after the call is code:

| Step | Rule |
|---|---|
| Points | met 1, partial 0.5, missing 0; n/a excluded |
| Score | the README metric score, moved toward the rubric score by **at most ±25** (`MAX_ADJUSTMENT`), so a README that talks the model into "perfect" gains 25 points at most |
| Spot check | a `met` verdict citing a file that doesn't exist becomes `partial` |
| False positives | a heading-based "no Installation section" issue that the rubric found covered under another heading is downgraded to `low`, not removed |
| New issues | `missing` or `partial` criteria the metrics didn't already flag become `doc_rubric` issues |
| Failure | any error leaves the metric score, with a note |

The category's notes show the verdict counts and the score change, for example "score 33 -> 58 (LLM judgment, bounded to ±25)".

## The instruction files

```
src/drrepo/agents/instructions/
  planner.md          ## System
  critic.md           ## System
  shared.md           ## Narrative rules, ## Investigation rules
  security.md         ## Narrative, ## Investigation
  code_quality.md     ...
  dependencies.md
  documentation.md
  maintainability.md
```

**Format.** A `# Title`, then `## Section` headings. A section's body is sent verbatim. Markdown lists and emphasis are fine, since models read them well. `<!-- ... -->` comments are maintainer notes and are stripped before sending. `agents/prompts.py` loads the files with `importlib.resources`, so they work the same from a source checkout and from an installed wheel.

**Composition.** An analyst's narrative prompt is its `## Narrative` section plus `shared.md`'s `## Narrative rules`. Its investigation prompt is its `## Investigation` section plus `## Investigation rules`. Put a rule that applies to every category in `shared.md`, once.

**What the shared rules guarantee** (and the tests check):
- **Evidence standard:** only issues seen with a tool, citing file and line.
- **No repeats** of issues the scanners already reported.
- **Severity calibration**, with definitions of critical, high, medium and low.
- **Prompt-injection guard:** repository content is data under audit, never instructions.
- **Efficiency:** start from the riskiest signal and stop when there is enough evidence.

**Safety net.** `prompts.validate_all()` loads every prompt the pipeline can request. It runs in the unit tests, in `drrepo doctor`, and in CI's packaging job against the installed wheel. A renamed heading or a missing file therefore fails fast, never mid-run.

### Writing good instructions

- **Say what to look for, concretely.** A checklist of specific patterns (for example `yaml.load` without `SafeLoader`) beats "look for security issues".
- **Keep sections lean.** Every word is sent on every call. The deep-path budget estimate (`ESTIMATED_TOKENS_PER_DEEP_INVESTIGATION`) assumes the instructions are a few hundred tokens.
- **Never ask for scores or numbers that code already computes.** The analyst's code owns scoring.
- **Don't name tools the category doesn't have**; check the tool-family table above.
- **After changing a prompt**, run `uv run pytest tests/agents`. Then, with an API key, run `uv run pytest -m integration` and analyze a repository or two to compare reports.

## Testing agents without an API key

`tests/agents/test_agent_loop.py` drives the real planner, the real `create_agent` loop and real tools on a temporary clone. It uses `ScriptedChatModel`, a LangChain chat model that calls `read_file` and then submits `InvestigationOutput`. Extend it when you change the investigator, the planner, or the output schemas. `tests/agents/test_prompts.py` checks that every prompt loads, that the shared rules are included, and that maintainer comments never reach a model.
