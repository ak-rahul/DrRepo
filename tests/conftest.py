"""Pytest configuration and shared fixtures."""
import pytest
from unittest.mock import Mock, MagicMock
from src.utils.config import Config


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    config = Config()
    config.groq_api_key = "test_groq_key_1234567890"
    config.github_token = "ghp_test_token_1234567890"
    config.tavily_api_key = "tvly_test_key_1234567890"
    config.model_provider = "groq"
    config.model_name = "llama-3.3-70b-versatile"
    config.temperature = 0.3
    return config


@pytest.fixture
def sample_repo_data():
    """Sample repository data for testing."""
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
        "size": 1024,
        "default_branch": "main",
        "open_issues": 5,
        "readme_content": """# Test Repository

## Installation

pip install test-repo

## Usage

from test_repo import TestClass
test = TestClass()
test.run()
## Features

- Feature 1: Fast processing
- Feature 2: Easy to use
- Feature 3: Well documented

## License

MIT License
""",
        "file_structure": {
            "has_tests": True,
            "has_ci": True,
            "has_docs": True,
            "has_license": True,
            "has_contributing": False,
            "has_changelog": False
        }
    }


@pytest.fixture
def sample_readme():
    """Sample README content for testing."""
    return """# Awesome Project

A comprehensive guide to using this amazing project.

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Features](#features)
- [Contributing](#contributing)
- [License](#license)

## Installation

Install the package using pip:

pip install awesome-project
## Usage

Basic usage example:

from awesome_project import AwesomeClass

Create instance
awesome = AwesomeClass()

Use it
result = awesome.do_something()
print(result)
## Features

- ⚡ Fast and efficient
- 🔒 Secure by default
- 📚 Well documented
- 🧪 Fully tested

## Contributing

Contributions are welcome! Please read our contributing guidelines.

## License

MIT License - see LICENSE file for details.
"""


@pytest.fixture
def sample_state():
    """Sample workflow state for testing."""
    return {
        "repo_url": "https://github.com/user/test-repo",
        "description": "Test repository description",
        "repo_data": {},
        "code_structure": {},
        "analysis": [],
        "metadata_recommendations": [],
        "content_improvements": [],
        "quality_review": [],
        "fact_check_results": [],
        "messages": [],
        "current_agent": "",
        "errors": []
    }


@pytest.fixture
def mock_llm_response():
    """Mock LLM response."""
    return """This is a well-structured repository with good documentation.

**Strengths:**
- Clear README with examples
- Good project structure
- Active maintenance

**Areas for Improvement:**
- Add more detailed API documentation
- Include contribution guidelines
- Add changelog for version history

**Overall Assessment:** Good (75/100)
"""


@pytest.fixture
def mock_github_client():
    """Mock GitHub API client."""
    mock = MagicMock()
    
    # Mock repository
    mock_repo = MagicMock()
    mock_repo.name = "test-repo"
    mock_repo.full_name = "user/test-repo"
    mock_repo.description = "Test repository"
    mock_repo.html_url = "https://github.com/user/test-repo"
    mock_repo.stargazers_count = 150
    mock_repo.forks_count = 25
    mock_repo.language = "Python"
    mock_repo.get_topics.return_value = ["python", "testing"]
    
    # Mock README
    mock_readme = MagicMock()
    mock_readme.decoded_content = b"# Test README\n\nThis is a test."
    mock_repo.get_readme.return_value = mock_readme
    
    mock.get_repo.return_value = mock_repo
    
    return mock
