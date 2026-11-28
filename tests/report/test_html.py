"""The self-contained HTML report: complete, script-free, and inert for repository text."""

import copy
from html.parser import HTMLParser

from drrepo.report.exporters import EXPORTERS, EXTENSIONS, FORMATS
from drrepo.report.html import to_html


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.hrefs += [v for k, v in attrs if k == "href" and v]


def _parse(html):
    parser = _Tags()
    parser.feed(html)
    return parser


def test_renders_every_section(report_dict):
    html = to_html(report_dict)
    assert html.startswith("<!doctype html>")
    assert f"{report_dict['overall_score']:.1f}" in html
    for heading in ("Categories", "Issues (", "Details"):
        assert heading in html
    assert "html" in FORMATS and EXPORTERS["html"] is to_html and EXTENSIONS["html"] == "html"


def test_repository_text_is_inert(report_dict):
    report = copy.deepcopy(report_dict)
    report["issues"][0]["title"] = '<script>alert(1)</script><img src=x onerror="alert(2)">'
    report["issues"][0]["description"] = "[click](javascript:alert(3))"
    report["repository"]["url"] = "javascript:alert(4)"
    report["repository"]["description"] = "</style><style>body{display:none}</style>"
    report["dependencies"] = [
        {
            "ecosystem": "PyPI",
            "name": "pkg",
            "version": "1.0",
            "scope": "runtime",
            "license": None,
            "vulnerabilities": ["GHSA-aaaa-bbbb-cccc", '"><script>x</script>'],
        }
    ]
    html = to_html(report)
    parsed = _parse(html)
    assert "script" not in parsed.tags and "img" not in parsed.tags
    assert parsed.tags.count("style") == 1  # only the report's own stylesheet
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert not any(h.startswith("javascript:") for h in parsed.hrefs)
    # Only well-formed advisory ids become links, and only to osv.dev.
    assert [h for h in parsed.hrefs if "osv.dev" in h] == [
        "https://osv.dev/vulnerability/GHSA-aaaa-bbbb-cccc"
    ]


def test_a_minimal_report_renders(report_dict):
    minimal = {
        "repository": {"name": "demo", "url": "https://github.com/octo/demo"},
        "overall_score": 50.0,
        "category_scores": {},
        "issues": [],
        "drrepo_version": "3",
        "generated_at": "2026-11-28T00:00:00Z",
    }
    html = to_html(minimal)
    assert "No issues." in html and 'href="https://github.com/octo/demo"' in html
