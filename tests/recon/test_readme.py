from drrepo.recon.readme import analyze_readme

FULL_README = """# Awesome

[![CI](https://img.shields.io/badge/ci-passing-green)](https://ci) ![Diagram](docs/arch.png)

## Table of Contents
- [Installation](#installation)
- [Usage](#usage)
- [License](#license)

## Features
Fast.

## Installation

```bash
pip install awesome
```

## Usage

```python
import awesome
```

See the [docs](https://example.com) and [guide](docs/guide.md).

## Documentation
Hosted online.

## Contributing
PRs welcome.

## Examples
See examples/.

## License
MIT
"""


def test_complete_readme_metrics():
    data = analyze_readme(FULL_README).data
    assert data["missing_sections"] == []
    assert data["code_block_count"] == 2
    assert data["badge_count"] == 1
    assert data["image_count"] == 2  # badge + diagram
    assert data["link_count"] >= 2
    assert data["has_table_of_contents"] is True
    assert data["quality_score"] > 60


def test_sections_come_from_headings_not_prose():
    data = analyze_readme("# Tool\n\nTo install, run the installer. Rapid API usage.\n").data
    assert "Installation" in data["missing_sections"]
    assert "Documentation" in data["missing_sections"]  # "rapid"/"api" in prose doesn't count


def test_headings_inside_code_fences_ignored():
    data = analyze_readme("# Real\n\n```\n## Installation\n```\n").data
    assert data["section_count"] == 1
    assert "Installation" in data["missing_sections"]


def test_setext_and_rst_headings():
    rst = "Project\n=======\n\nInstallation\n------------\n\npip install x\n"
    data = analyze_readme(rst).data
    assert data["section_count"] == 2
    assert "Installation" not in data["missing_sections"]


def test_empty_readme():
    result = analyze_readme("   ")
    assert result.data["quality_score"] == 0.0
    assert len(result.data["missing_sections"]) == 7
    assert result.detail == "No README content found"


def test_score_is_bounded():
    assert 0 <= analyze_readme("x").data["quality_score"] <= 100
    assert analyze_readme(FULL_README * 5).data["quality_score"] <= 100
