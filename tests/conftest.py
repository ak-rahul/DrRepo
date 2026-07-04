"""Pytest configuration and shared fixtures.

Every fixture here builds objects directly with fake values -- nothing reads
`os.environ` or a `.env` file. This is what makes the unit suite hermetic:
`pytest -m "not integration"` must pass with zero environment variables set.
"""

from unittest.mock import Mock

import pytest

from src.config import Config


@pytest.fixture
def fake_llm_client(mock_llm_response):
    """A fake chat-model client satisfying `LLMClient` -- no real network/API key needed."""
    client = Mock()
    client.invoke = Mock(return_value=Mock(content=mock_llm_response))
    return client


@pytest.fixture
def fake_config() -> Config:
    """A fully-populated fake Config, built directly (no env/.env involved)."""
    return Config(
        groq_api_key="test_groq_key_1234567890",
        github_token="test_gh_token_1234567890",
        model_provider="groq",
        model_name="llama-3.3-70b-versatile",
        temperature=0.3,
    )


@pytest.fixture
def sample_repo_data():
    """Sample repository metadata, shaped like `collect_github_metadata`'s output."""
    return {
        "name": "test-repo",
        "full_name": "user/test-repo",
        "description": "A test repository for unit testing",
        "url": "https://github.com/user/test-repo",
        "stars": 150,
        "forks": 25,
        "watchers": 100,
        "language": "Python",
        "topics": ["python", "testing", "automation"],
        "license": "MIT",
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "pushed_at": "2025-01-10T00:00:00Z",
        "size_kb": 1024,
        "default_branch": "main",
        "open_issues": 5,
        "readme_content": "# Test Repository\n\n## Installation\n\npip install test-repo\n",
        "file_structure": {
            "has_tests": True,
            "has_ci": True,
            "has_docs": True,
            "has_license": True,
            "has_contributing": False,
            "has_changelog": False,
        },
    }


@pytest.fixture
def sample_readme_with_badges_and_images():
    """Real markdown fixture used to lock in correct image/link/badge counts."""
    return """# Awesome Project

[![Tests](https://img.shields.io/badge/tests-passing-green)](https://example.com/ci)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

![Architecture diagram](docs/architecture.png)

## Table of Contents
- [Installation](#installation)
- [Usage](#usage)

## Installation

Install the package using pip:

```
pip install awesome-project
```

## Usage

```python
from awesome_project import AwesomeClass
awesome = AwesomeClass()
```

See the [full docs](https://example.com/docs) and our [contributing guide](CONTRIBUTING.md).

## License

MIT License - see LICENSE file for details.
"""


@pytest.fixture
def mock_llm_response():
    """Mock LLM response text used by analyst-agent tests."""
    return """This is a well-structured repository with good documentation.

**Strengths:**
- Clear README with examples
- Good project structure

**Areas for Improvement:**
- Add more detailed API documentation
- Add a changelog

**Overall Assessment:** Good (75/100)
"""
