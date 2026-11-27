"""DrRepo: an agentic multi-agent auditor for public GitHub repositories."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("drrepo")
except PackageNotFoundError:  # pragma: no cover - running from a bare source tree
    __version__ = "0.0.0+unknown"
