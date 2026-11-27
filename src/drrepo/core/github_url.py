"""Parse and normalize GitHub repository URLs.

Accepts the forms people actually paste -- `https://github.com/o/r`,
`.../o/r.git`, `.../o/r/tree/main/sub`, `github.com/o/r`, `www.github.com/...`
-- and rejects anything that isn't a plain public github.com repository. The
normalized clone URL is what reaches `git`, so nothing user-supplied beyond a
validated owner/name pair is ever passed on a command line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})$")


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.full_name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.full_name}.git"


def parse_github_url(url: str) -> RepoRef:
    """Return the `RepoRef` for a GitHub repository URL.

    Raises:
        ValueError: with a user-presentable message if `url` isn't a GitHub repo URL.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Repository URL cannot be empty")
    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("https", "http") or host not in ("github.com", "www.github.com"):
        raise ValueError("Only https://github.com/<owner>/<repo> URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("Repository URLs must not contain credentials")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Expected a URL of the form https://github.com/<owner>/<repo>")

    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    if not _NAME_RE.match(owner) or not _NAME_RE.match(name) or name in (".", ".."):
        raise ValueError(f"'{owner}/{name}' is not a valid GitHub repository name")
    return RepoRef(owner=owner, name=name)
