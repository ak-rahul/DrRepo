# Examples

Run each one from the repository root after `uv sync`. They read `.env` the same way the CLI does. Without an LLM API key they still work: the run is deterministic, with no LLM summaries and no deep investigation.

| File | Shows |
|---|---|
| [basic_usage.py](basic_usage.py) | One analysis from Python: scores, top issues, quick wins, saving JSON/Markdown/SARIF |
| [compare_repositories.py](compare_repositories.py) | Ranking several repositories with one shared `AnalysisService` (shared circuit breaker and dependency cache, per-run token budget) |
| [policy_gate.py](policy_gate.py) | A CI gate with a custom policy (overall score, per-category floor, blocking issues) that writes SARIF and emits GitHub annotations |
| [custom_collector.py](custom_collector.py) | Extending the pipeline with a new recon collector and an analyst that scores its output |
| [mcp_client.py](mcp_client.py) | Driving `drrepo mcp` over stdio from Python: listing tools, a tool call with progress notifications, reading a report resource |
| [mcp_client_config.json](mcp_client_config.json) | A Claude Desktop / stdio MCP client config template |
| [github-workflow.yml](github-workflow.yml) | A drop-in workflow using the DrRepo action: score gate, SARIF upload, SBOM, and a pull request summary comment |

```bash
uv run python examples/basic_usage.py https://github.com/pallets/itsdangerous --shallow
uv run python examples/compare_repositories.py https://github.com/encode/httpx https://github.com/psf/requests
uv run python examples/policy_gate.py https://github.com/pallets/itsdangerous --min-score 70
uv run python examples/custom_collector.py https://github.com/psf/requests
uv run python examples/mcp_client.py https://github.com/pallets/itsdangerous
```

`tests/test_examples.py` imports every script and covers their own logic, so a breaking API change fails CI instead of silently rotting an example.
