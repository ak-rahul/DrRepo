"""README structural analysis.

v1 had broken regexes here (mangled `[...]`/`(...)` groups) that made image,
link, and badge counts always wrong -- verified during the audit. Fixed and
given real unit tests this time. Pure function of text, no I/O, so it's
trivial to test and doesn't need to be a "collector" with network access.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.models import CollectorResult, CollectorStatus

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")
_LINK_RE = re.compile(r"(?<!!)\[.*?\]\(.*?\)")
_BADGE_RE = re.compile(r"!\[.*?\]\((https?://[^)]*?(?:badge|shields\.io)[^)]*?)\)", re.IGNORECASE)
_TOC_LINK_RE = re.compile(r"[-*]\s*\[.*?\]\(#.*?\)")

_ESSENTIAL_SECTIONS = {
    "installation": ["install", "setup", "getting started"],
    "usage": ["usage", "how to use", "quick start"],
    "features": ["features", "capabilities"],
    "documentation": ["documentation", "docs", "api"],
    "contributing": ["contributing", "contribution"],
    "license": ["license"],
    "examples": ["examples", "demo"],
}

_TOC_HEADING_PATTERNS = [
    r"##\s*Table of Contents",
    r"##\s*Contents",
    r"##\s*TOC",
]


def _count_words(content: str) -> int:
    stripped = _CODE_FENCE_RE.sub("", content)
    return len(stripped.split())


def _count_sections(content: str) -> int:
    return len(_HEADING_RE.findall(content))


def _count_code_blocks(content: str) -> int:
    return len(re.findall(r"```", content)) // 2


def _count_images(content: str) -> int:
    return len(_IMAGE_RE.findall(content))


def _count_links(content: str) -> int:
    return len(_LINK_RE.findall(content))


def _count_badges(content: str) -> int:
    return len(_BADGE_RE.findall(content))


def _has_toc(content: str) -> bool:
    if any(re.search(p, content, re.IGNORECASE) for p in _TOC_HEADING_PATTERNS):
        return True
    return bool(_TOC_LINK_RE.search(content))


def _find_missing_sections(content: str) -> List[str]:
    content_lower = content.lower()
    missing = []
    for section, keywords in _ESSENTIAL_SECTIONS.items():
        if not any(keyword in content_lower for keyword in keywords):
            missing.append(section.title())
    return missing


def _calculate_quality_score(analysis: Dict[str, Any]) -> float:
    score = 0.0

    word_count = analysis["word_count"]
    if word_count >= 1000:
        score += 20
    elif word_count >= 500:
        score += 15
    elif word_count >= 300:
        score += 10
    elif word_count >= 100:
        score += 5

    score += min(analysis["section_count"] * 3, 20)
    score += min(analysis["code_block_count"] * 5, 15)
    score += min(analysis["image_count"] * 3, 10)
    score -= min(len(analysis["missing_sections"]) * 5, 30)

    if analysis["has_table_of_contents"]:
        score += 5
    if analysis["badge_count"] > 0:
        score += 5
    score += min(analysis["link_count"] * 2, 10)

    return float(max(0.0, min(100.0, score)))


def analyze_readme(content: str) -> CollectorResult:
    """Analyze README markdown content and return structural metrics."""
    if not content:
        data = {
            "word_count": 0,
            "section_count": 0,
            "code_block_count": 0,
            "image_count": 0,
            "link_count": 0,
            "badge_count": 0,
            "missing_sections": [s.title() for s in _ESSENTIAL_SECTIONS],
            "has_table_of_contents": False,
            "quality_score": 0.0,
        }
        return CollectorResult(
            name="readme",
            status=CollectorStatus.OK,
            data=data,
            detail="No README content found",
        )

    data = {
        "word_count": _count_words(content),
        "section_count": _count_sections(content),
        "code_block_count": _count_code_blocks(content),
        "image_count": _count_images(content),
        "link_count": _count_links(content),
        "badge_count": _count_badges(content),
        "missing_sections": _find_missing_sections(content),
        "has_table_of_contents": _has_toc(content),
    }
    data["quality_score"] = _calculate_quality_score(data)

    return CollectorResult(name="readme", status=CollectorStatus.OK, data=data)


def generate_improvement_suggestions(analysis: Dict[str, Any]) -> List[Dict[str, str]]:
    """Deterministic, non-LLM improvement suggestions from README metrics."""
    suggestions = []

    if analysis.get("word_count", 0) < 300:
        suggestions.append(
            {
                "priority": "high",
                "suggestion": "README is too short. Add more detailed explanation.",
            }
        )
    if analysis.get("code_block_count", 0) == 0:
        suggestions.append({"priority": "high", "suggestion": "Add code examples."})
    if analysis.get("image_count", 0) == 0:
        suggestions.append({"priority": "medium", "suggestion": "Add screenshots or diagrams."})
    if not analysis.get("has_table_of_contents", False) and analysis.get("section_count", 0) > 5:
        suggestions.append({"priority": "medium", "suggestion": "Add a table of contents."})
    if analysis.get("badge_count", 0) == 0:
        suggestions.append(
            {"priority": "low", "suggestion": "Add badges (build status, version, etc.)."}
        )

    return suggestions
