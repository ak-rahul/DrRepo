"""Provenance: what produced a report, so two reports can be compared fairly.

Recorded in every report under `provenance`:

- `instructions`: a short SHA-256 of each agent instructions file, computed
  over the text actually sent to models (maintainer comments excluded), so a
  prompt change is visible and a comment edit isn't;
- `llm`: the provider and model, or null when the run used no LLM;
- `tools`: the version of each external scanner (null if not installed).

Scanner versions are looked up once per process; instruction hashes once per
process too (the files ship in the package and don't change while running).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from functools import cache
from typing import Any

from drrepo.agents import prompts
from drrepo.config import Config
from drrepo.models import Category
from drrepo.recon.scanners import find_executable

TOOLS = ("git", "ruff", "bandit", "semgrep", "zizmor", "hadolint")
_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)*")
INSTRUCTION_FILES = ("planner", "shared", *(c.value for c in Category))


@cache
def tool_version(tool: str) -> str | None:
    exe = "git" if tool == "git" else find_executable(tool)
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _VERSION_RE.search(proc.stdout or proc.stderr or "")
    return match.group(0) if match else None


@cache
def instruction_hashes() -> dict[str, str]:
    hashes = {}
    for name in INSTRUCTION_FILES:
        sent = json.dumps(prompts.sections(name), sort_keys=True)
        hashes[name] = hashlib.sha256(sent.encode("utf-8")).hexdigest()[:12]
    return hashes


def build_provenance(config: Config, llm_used: bool) -> dict[str, Any]:
    return {
        "instructions": dict(instruction_hashes()),
        "llm": {
            "provider": config.model_provider,
            "model": config.model_for(),
            "roles": config.models_by_role(),
        }
        if llm_used
        else None,
        "tools": {tool: tool_version(tool) for tool in TOOLS},
    }
