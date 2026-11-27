"""README structural analysis. Pure function of text: no I/O, trivially testable.

Section detection looks at *headings*, not the whole body, so a README that
merely mentions "install" in a sentence isn't credited with an Installation
section, and "api" no longer matches words like "rapid".

`data` schema: word_count, section_count, code_block_count, image_count,
link_count, badge_count, missing_sections, has_table_of_contents, quality_score
"""

from __future__ import annotations

import re
from typing import Any

from drrepo.models import CollectorResult, CollectorStatus

NAME = "readme"

_CODE_FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.DOTALL | re.MULTILINE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_SETEXT_HEADING_RE = re.compile(r"^(\S.*)\n(?:=+|-+)\s*$", re.MULTILINE)
# `=`/`-` underlines are already matched by the setext pattern; only other rST
# adornments here, or every such heading would be counted twice.
_RST_HEADING_RE = re.compile(r"^(\S.*)\n([~^\"'`#*+])\2{2,}\s*$", re.MULTILINE)
# README text is attacker-controlled, so every pattern below is linear-time:
# character classes exclude the opening delimiter and newlines, so a failed
# match attempt can never rescan text that a later attempt will scan again.
# (The earlier `\[[^\]]*\]` forms were quadratic: 30k "[" took ~1 s, and a TOC
# pattern with `^\s*` took 7 s on 30k newlines.)
_IMAGE_RE = re.compile(r"!\[[^\[\]\n]*\]\([^()\n]*\)|<img\s[^<>]*>", re.IGNORECASE)
_LINK_RE = re.compile(r"(?<!!)\[[^\[\]\n]*\]\([^()\n]*\)")
_BADGE_RE = re.compile(
    r"!\[[^\[\]\n]*\]\((https?://[^()\s]*?(?:badge|shields\.io)[^()\s]*)\)", re.IGNORECASE
)
_TOC_LINK_RE = re.compile(r"^[ \t]*[-*][ \t]*\[[^\[\]\n]+\]\(#[^()\n]*\)", re.MULTILINE)
_TOC_HEADING_RE = re.compile(r"^(table of )?contents$|^toc$", re.IGNORECASE)

# Applied here, not only by callers: the GitHub API, the clone, and the MCP
# `analyze_readme_text` tool all feed this function.
MAX_README_CHARS = 100_000

_ESSENTIAL_SECTIONS: dict[str, tuple[str, ...]] = {
    "Installation": ("install", "setup", "getting started", "quick start", "quickstart"),
    "Usage": ("usage", "how to use", "quick start", "quickstart", "getting started", "example"),
    "Features": ("feature", "capabilities", "overview", "what is", "about", "why"),
    "Documentation": ("documentation", "docs", "api reference", "reference", "guide"),
    "Contributing": ("contribut", "development", "developing"),
    "License": ("license", "licence"),
    "Examples": ("example", "demo", "tutorial", "usage"),
}


def _headings(content: str) -> list[str]:
    stripped = _CODE_FENCE_RE.sub("", content)
    found = [m.group(1) for m in _HEADING_RE.finditer(stripped)]
    found += [m.group(1) for m in _SETEXT_HEADING_RE.finditer(stripped)]
    found += [m.group(1) for m in _RST_HEADING_RE.finditer(stripped)]
    return [h.strip().strip("*_`").lower() for h in found]


def _find_missing_sections(headings: list[str]) -> list[str]:
    return [
        section
        for section, keywords in _ESSENTIAL_SECTIONS.items()
        if not any(any(k in h for k in keywords) for h in headings)
    ]


def _quality_score(a: dict[str, Any]) -> float:
    words = a["word_count"]
    score = (
        20.0
        if words >= 800
        else 15.0
        if words >= 400
        else 10.0
        if words >= 200
        else 5.0
        if words >= 80
        else 0.0
    )
    score += min(a["section_count"] * 3, 20)
    score += min(a["code_block_count"] * 5, 15)
    score += min(a["image_count"] * 3, 6)
    score += min(a["link_count"], 10)
    score += 4 if a["badge_count"] else 0
    score += 5 if a["has_table_of_contents"] else 0
    # Each missing essential section costs 3; the 7-section total (21) plus
    # the 80-point positive range keeps a complete, well-structured README near 100.
    score += 20 - 3 * len(a["missing_sections"])
    return float(max(0.0, min(100.0, score)))


def analyze_readme(content: str) -> CollectorResult:
    """Analyze README markdown/rST text and return structural metrics.

    Content beyond `MAX_README_CHARS` is ignored (and noted in `detail`).
    """
    truncated = bool(content) and len(content) > MAX_README_CHARS
    content = (content or "")[:MAX_README_CHARS]
    if not content.strip():
        data: dict[str, Any] = {
            "word_count": 0,
            "section_count": 0,
            "code_block_count": 0,
            "image_count": 0,
            "link_count": 0,
            "badge_count": 0,
            "missing_sections": list(_ESSENTIAL_SECTIONS),
            "has_table_of_contents": False,
            "quality_score": 0.0,
        }
        return CollectorResult(
            name=NAME, status=CollectorStatus.OK, data=data, detail="No README content found"
        )

    headings = _headings(content)
    prose = _CODE_FENCE_RE.sub("", content)
    data = {
        "word_count": len(prose.split()),
        "section_count": len(headings),
        "code_block_count": len(_CODE_FENCE_RE.findall(content))
        + content.count("\n.. code-block::"),
        "image_count": len(_IMAGE_RE.findall(content)),
        "link_count": len(_LINK_RE.findall(content)),
        "badge_count": len(_BADGE_RE.findall(content)),
        "missing_sections": _find_missing_sections(headings),
        "has_table_of_contents": any(_TOC_HEADING_RE.match(h) for h in headings)
        or len(_TOC_LINK_RE.findall(content)) >= 3,
    }
    data["quality_score"] = _quality_score(data)
    detail = f"README truncated to the first {MAX_README_CHARS:,} characters" if truncated else None
    return CollectorResult(name=NAME, status=CollectorStatus.OK, data=data, detail=detail)
