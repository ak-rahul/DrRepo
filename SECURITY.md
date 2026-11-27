# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue.

Include the DrRepo version (`uv run drrepo --version`), the interface involved (CLI, web UI, MCP server, health API), and steps to reproduce. If a specific repository triggers the problem, link it. You should get a first response within 7 days.

## Supported versions

Only the latest release on `main` receives security fixes.

## Scope

DrRepo processes untrusted input by design: it clones arbitrary public repositories and gives an LLM tool access to their contents. The protections it relies on are described in the [security model](docs/architecture.md#security-model). In scope:

- code from an analyzed repository being executed, installed, or imported;
- reading or writing files outside the temporary clone, for example through investigator tool arguments, symlinks, or path traversal;
- secrets (API keys, `GH_TOKEN`) leaking into reports, logs, SARIF output, or LLM prompts;
- bypasses of the clone hardening (size caps, `core.symlinks=false`, no credential prompts, LFS skipped).

Out of scope:

- The MCP server's HTTP transports have no authentication of their own. This is documented. Run them behind your own authentication or on a trusted network only.
- Scores and findings that are wrong without any of the effects above. Report those as normal bugs.
- Vulnerabilities in dependencies that DrRepo doesn't reach. CI runs `pip-audit` on every change, and Dependabot proposes updates weekly.
