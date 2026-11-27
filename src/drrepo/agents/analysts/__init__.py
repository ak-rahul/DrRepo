"""One analyst per report category. Each owns its deterministic findings + scoring and
the prompts used for both the shallow and deep paths."""

from __future__ import annotations

from drrepo.agents.analysts.base import Analyst
from drrepo.models import Category


def default_analysts() -> dict[Category, Analyst]:
    """One instance of every category analyst, keyed by category."""
    from drrepo.agents.analysts.code_quality import CodeQualityAnalyst
    from drrepo.agents.analysts.dependencies import DependencyAnalyst
    from drrepo.agents.analysts.documentation import DocumentationAnalyst
    from drrepo.agents.analysts.maintainability import MaintainabilityAnalyst
    from drrepo.agents.analysts.security import SecurityAnalyst

    analysts: list[Analyst] = [
        DocumentationAnalyst(),
        CodeQualityAnalyst(),
        SecurityAnalyst(),
        DependencyAnalyst(),
        MaintainabilityAnalyst(),
    ]
    return {a.category: a for a in analysts}
