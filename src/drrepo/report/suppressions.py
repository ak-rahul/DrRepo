"""Suppressions: accept a known, reviewed finding without disabling the check.

A CI gate that can't accept a finding someone has reviewed ends up disabled.
Suppressions let a team record that decision in a file, with a reason and,
ideally, an expiry date:

    # .drrepo.toml
    [[suppress]]
    rule = "bandit/B605"                      # the SARIF rule id: "<source>/<rule_id>"
    path = "src/click/_termui_impl.py"        # optional fnmatch glob on the issue's file
    reason = "Launches $PAGER by design; input is the user's own environment"
    expires = 2027-06-30                      # optional; the finding returns after this date

`rule` may also be `"<source>/*"` (every rule from one tool) or a bare source
for rule-less checks (e.g. `"readme_analyzer"`).

Trust model. A suppression file *you* pass (`--suppressions`, `SUPPRESSIONS_FILE`)
always applies. A `.drrepo.toml` inside the analyzed repository applies only
with `TRUST_REPO_SUPPRESSIONS=true`: when auditing third-party code, the
repository must not be able to hide its own findings. Either way, suppressed
issues stay in the report (with reason and origin) and in SARIF as native
`suppressions`; they are only excluded from scores and quick wins.
"""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from drrepo.errors import DrRepoError
from drrepo.models import Issue, rule_key

REPOSITORY_FILE = ".drrepo.toml"


class SuppressionError(DrRepoError):
    """A suppression file is malformed. The message names the file and entry."""


@dataclass(frozen=True)
class Suppression:
    rule: str
    reason: str
    path: str | None = None
    expires: date | None = None
    origin: str = "local"  # "local" (a file you passed) or "repository" (the repo's .drrepo.toml)

    def matches(self, issue: Issue) -> bool:
        key = rule_key(issue.source, issue.rule_id)
        if self.rule.endswith("/*"):
            rule_ok = key.split("/", 1)[0] == self.rule[:-2]
        else:
            rule_ok = key == self.rule
        if not rule_ok:
            return False
        if self.path is None:
            return True
        return issue.file is not None and fnmatch.fnmatch(issue.file, self.path)

    def expired(self, today: date) -> bool:
        return self.expires is not None and today > self.expires

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "path": self.path,
            "reason": self.reason,
            "expires": self.expires.isoformat() if self.expires else None,
            "origin": self.origin,
        }


def parse(text: str, *, origin: str, source_name: str) -> list[Suppression]:
    """Parse `[[suppress]]` entries. Raises SuppressionError naming the bad entry."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SuppressionError(f"{source_name}: not valid TOML ({e})") from e
    entries = data.get("suppress", [])
    if not isinstance(entries, list):
        raise SuppressionError(f"{source_name}: 'suppress' must be an array of tables")
    result = []
    for n, raw in enumerate(entries, start=1):
        where = f"{source_name}: suppress #{n}"
        if not isinstance(raw, dict):
            raise SuppressionError(f"{where} is not a table")
        rule, reason = raw.get("rule"), raw.get("reason")
        if not isinstance(rule, str) or not rule.strip():
            raise SuppressionError(f"{where} needs a 'rule' such as \"bandit/B602\"")
        if not isinstance(reason, str) or not reason.strip():
            raise SuppressionError(f"{where} ({rule}) needs a non-empty 'reason'")
        path = raw.get("path")
        if path is not None and (not isinstance(path, str) or not path.strip()):
            raise SuppressionError(f"{where} ({rule}): 'path' must be a non-empty glob")
        expires = raw.get("expires")
        if isinstance(expires, str):
            try:
                expires = date.fromisoformat(expires)
            except ValueError as e:
                raise SuppressionError(f"{where} ({rule}): 'expires' must be YYYY-MM-DD") from e
        if expires is not None and not isinstance(expires, date):
            raise SuppressionError(f"{where} ({rule}): 'expires' must be a date")
        unknown = set(raw) - {"rule", "reason", "path", "expires"}
        if unknown:
            raise SuppressionError(f"{where} ({rule}): unknown keys {sorted(unknown)}")
        result.append(
            Suppression(
                rule=rule.strip(),
                reason=reason.strip(),
                path=path.strip() if path else None,
                expires=expires,
                origin=origin,
            )
        )
    return result


def load_file(path: Path, *, origin: str = "local") -> list[Suppression]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SuppressionError(f"{path}: cannot read suppression file ({e})") from e
    return parse(text, origin=origin, source_name=str(path))


@dataclass
class SuppressionResult:
    kept: list[Issue] = field(default_factory=list)
    suppressed: list[tuple[Issue, Suppression]] = field(default_factory=list)
    expired: list[Suppression] = field(default_factory=list)  # matched, but past `expires`

    def notes(self) -> list[str]:
        notes = []
        if self.suppressed:
            notes.append(
                f"{len(self.suppressed)} issue(s) suppressed and excluded from the score "
                "(listed under suppressed, with reasons)."
            )
        notes.extend(
            f"Suppression for {s.rule}{f' ({s.path})' if s.path else ''} expired on "
            f"{s.expires}; the finding counts again."
            for s in self.expired
        )
        return notes


def apply(issues: list[Issue], suppressions: list[Suppression], today: date) -> SuppressionResult:
    """Split `issues` into kept and suppressed. The first matching active suppression wins."""
    result = SuppressionResult()
    if not suppressions:
        result.kept = list(issues)
        return result
    expired_seen: dict[int, Suppression] = {}
    for issue in issues:
        matched = None
        for index, suppression in enumerate(suppressions):
            if not suppression.matches(issue):
                continue
            if suppression.expired(today):
                expired_seen.setdefault(index, suppression)
                continue
            matched = suppression
            break
        if matched is None:
            result.kept.append(issue)
        else:
            result.suppressed.append((issue, matched))
    result.expired = list(expired_seen.values())
    return result


def baseline_toml(issues: list[dict[str, Any]], *, reason: str, expires: date | None) -> str:
    """A suppression file accepting every given issue (one entry per rule and file)."""
    seen: set[tuple[str, str | None]] = set()
    lines = [
        "# DrRepo suppressions: accepted, reviewed findings (see `drrepo baseline --help`).",
        "# Replace each generic reason with the actual justification before committing.",
        "",
    ]
    for issue in issues:
        key = (
            rule_key(issue.get("source") or issue["category"], issue.get("rule_id")),
            issue.get("file"),
        )
        if key in seen:
            continue
        seen.add(key)
        lines += ["[[suppress]]", f"rule = {_toml_str(key[0])}"]
        if key[1]:
            lines.append(f"path = {_toml_str(key[1])}")
        title = str(issue["title"])[:100]
        lines.append(f"reason = {_toml_str(reason + ': ' + title)}")
        if expires:
            lines.append(f"expires = {expires.isoformat()}")
        lines.append("")
    return "\n".join(lines)


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'
