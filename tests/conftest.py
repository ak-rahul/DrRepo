"""Pytest configuration and fixtures."""
import pytest
import os
from unittest.mock import Mock, patch
from src.utils.config import Config

@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    config = Config()
    config.openai_api_key = "test-openai-key"
    config.github_token = "test-github-token"
    config.tavily_api_key = "test-tavily-key"
    return config

@pytest.fixture
def sample_repo_data():
    """Sample repository data for testing."""
    return {
        "name": "test-repo",
        "full_name": "testuser/test-repo",
        "description": "A test repository",
        "url": "https://github.com/testuser/test-repo",
        "stars": 100,
        "forks": 20,
        "watchers": 50,
        "open_issues": 5,
        "language": "Python",
        "topics": ["python", "testing", "automation"],
        "license": "MIT",
        "has_wiki": True,
        "has_issues": True,
        "has_projects": False,
        "readme_content": "# Test Repo\n\nThis is a test repository.\n\n## Installation\n\n``````",
        "file_structure": {
            "files": ["README.md", "setup.py", "requirements.txt"],
            "directories": ["tests", "src"],
            "has_tests": True,
            "has_docs": False,
            "has_ci": True,
            "has_requirements": True,
            "has_setup": True,
            "has_docker": False,
            "has_makefile": False,
        }
    }

@pytest.fixture
def sample_readme_analysis():
    """Sample README analysis for testing."""
    return {
        "has_main_title": True,
        "title": "Test Repo",
        "section_count": 3,
        "word_count": 150,
        "has_installation": True,
        "has_usage": True,
        "has_examples": False,
        "has_contributing": False,
        "has_license": False,
        "has_code_blocks": True,
        "badge_count": 0,
        "image_count": 0,
        "quality_score": 65.0,
        "missing_sections": ["Examples", "Contributing", "License"]
    }

@pytest.fixture
def mock_github_client():
    """Mock GitHub client."""
    with patch('src.tools.github_tool.Github') as mock:
        yield mock

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client."""
    with patch('src.agents.base_agent.ChatOpenAI') as mock:
        yield mock
