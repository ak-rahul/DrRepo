# Security model

DrRepo points scanners and an LLM agent at arbitrary public code. These invariants keep that safe.

## Never execute the analyzed code

- Nothing from the clone is installed, built, imported, or run. No `pip install`, `npm install`, setup scripts, or test runs.
- ruff, bandit, and semgrep only parse source. ruff runs with `--isolated`, so the repository's config can't change which rules run.
- Manifests and lockfiles are parsed as text (TOML/JSON/line-based). They are never resolved by a package manager.

## Hardened clone (`collectors/clone.py`)

| Measure | Why |
|---|---|
| URL normalized to `https://github.com/<owner>/<repo>.git`, validated against a strict name pattern, passed after `--` | no option injection, no credentials in URLs, no other hosts |
| `GIT_TERMINAL_PROMPT=0`, empty `credential.helper`, `GCM_INTERACTIVE=never`, stdin closed | a private or missing repo fails immediately instead of hanging on a prompt or a Windows credential dialog |
| `core.symlinks=false` | symlinks are checked out as plain files, so nothing in the clone can point outside it |
| `GIT_LFS_SKIP_SMUDGE=1`, `--depth 1 --single-branch --no-tags` | bounded download |
| size cap (`CLONE_MAX_SIZE_MB`) and timeout | oversized repos are deleted and skipped |
| temp dir removed in `finally` (read-only pack files handled on Windows) | no leftovers, whatever the outcome |

## LLM-controlled tool arguments

The investigator chooses tool arguments, so every tool treats them as untrusted:

- `resolve_safe_path` resolves paths under the clone root and rejects anything outside it, including `..`, absolute paths, NUL bytes, and symlink targets.
- Globs containing `..`, an absolute path, or a drive letter are rejected.
- Regex patterns are length-capped, and lines longer than 2000 characters are skipped.
- Read sizes, listing sizes, match counts, and scanner output are capped.
- Tools are read-only. There is no tool that writes files, runs commands, or reaches arbitrary URLs.

Prompt injection inside the analyzed repository (for example a README that tells the agent to ignore its instructions) can at worst skew that category's narrative or its agent-reported issues. Those issues carry `source: investigator:<category>` so readers can weigh them. It cannot change deterministic findings or scores, which never come from LLM text.

## Data handling

- The secret scanner reports a secret's type and location, never its value.
- Only the following leave the machine: the repository's public metadata, sent to GitHub; package names and versions, sent to OSV.dev and deps.dev; trimmed recon data and tool outputs, sent to your configured LLM provider.
- Credentials come from the environment at runtime. The Docker image contains none and runs as a non-root user.

## Exposed services

The health API and MCP HTTP transport have no authentication. Bind them to localhost (the default) or put them behind an authenticating proxy. An exposed MCP server lets anyone trigger clones and spend your LLM quota.
