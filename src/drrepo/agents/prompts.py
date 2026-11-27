"""Agent instructions, loaded from the markdown files in `agents/instructions/`.

Each agent's job is written as a document, not as string constants in code:

    instructions/planner.md          ## System                 the Lead Investigator
    instructions/<category>.md       ## Narrative              shallow-path summary prompt
                                     ## Investigation          deep-path ReAct system prompt
    instructions/documentation.md    ## Rubric                 the bounded README rubric (agents/rubric.py)
    instructions/shared.md           ## Narrative rules        appended to every Narrative
                                     ## Investigation rules    appended to every Investigation

Format: a `# Title`, then `## Section` headings whose bodies are sent verbatim
(Markdown is fine; models read it well). `<!-- ... -->` comments are maintainer
notes and are stripped, so they never reach a model. The files ship inside the
wheel and are read through `importlib.resources`, so they work from an
installed package, a zip, or a source checkout alike.

Every prompt the code can request is checked by `validate_all()` (run in tests,
`drrepo doctor`, and CI's packaging job), so a renamed heading or missing file
fails fast instead of mid-run.
"""

from __future__ import annotations

import re
from functools import cache
from importlib.resources import files

from drrepo.errors import DrRepoError
from drrepo.models import Category

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class InstructionsError(DrRepoError):
    """An instruction file or a required section in it is missing or empty."""


@cache
def _sections(name: str) -> dict[str, str]:
    """`{lower-cased heading: body}` for every `## heading` in `instructions/<name>.md`."""
    resource = files("drrepo.agents") / "instructions" / f"{name}.md"
    try:
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        raise InstructionsError(f"agent instructions file {name}.md not found") from e

    sections: dict[str, str] = {}
    heading: str | None = None
    body: list[str] = []
    for line in _COMMENT_RE.sub("", text).splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections[heading] = "\n".join(body).strip()
            heading, body = line[3:].strip().lower(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections[heading] = "\n".join(body).strip()
    return sections


def sections(name: str) -> dict[str, str]:
    """Every section of `instructions/<name>.md`, as sent to models (comments stripped)."""
    return dict(_sections(name))


def section(name: str, heading: str) -> str:
    """The body of `## <heading>` in `instructions/<name>.md`.

    Raises:
        InstructionsError: the file, the section, or its body is missing.
    """
    body = _sections(name).get(heading.lower(), "")
    if not body:
        raise InstructionsError(f"{name}.md has no non-empty '## {heading}' section")
    return body


def planner_prompt() -> str:
    return section("planner", "System")


def narrative_prompt(category: Category) -> str:
    return f"{section(category.value, 'Narrative')}\n\n{section('shared', 'Narrative rules')}"


def investigation_prompt(category: Category) -> str:
    return (
        f"{section(category.value, 'Investigation')}\n\n{section('shared', 'Investigation rules')}"
    )


def validate_all() -> None:
    """Load every prompt the pipeline can request. Raises `InstructionsError`."""
    planner_prompt()
    section("documentation", "Rubric")
    for category in Category:
        narrative_prompt(category)
        investigation_prompt(category)
