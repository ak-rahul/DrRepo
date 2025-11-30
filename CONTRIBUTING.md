# 🤝 Contributing to DrRepo

Thank you for your interest in contributing to DrRepo! We welcome contributions from everyone.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Pull Request Process](#pull-request-process)
- [Community](#community)

---

## 📜 Code of Conduct

This project adheres to the [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.9 or higher
- Git
- GitHub account

### Development Environment

1. **Fork the repository**
   - Click "Fork" on the GitHub repository page

2. **Clone your fork**
```
git clone https://github.com/ak-rahul/DrRepo.git
cd DrRepo
```

3. **Add upstream remote**
```
git remote add upstream https://github.com/ak-rahul/DrRepo.git
```

---

## 🛠️ Development Setup

### 1. Create Virtual Environment

```
python -m venv venv
```

Activate (Windows)
```
venv\Scripts\activate
```

Activate (Linux/Mac)
```
source venv/bin/activate
```


### 2. Install Dependencies

Install production dependencies
```
pip install -r requirements.txt
```

Install development dependencies
```
pip install -r requirements-dev.txt
```


### 3. Install Pre-commit Hooks

```
pre-commit install
```


### 4. Set Up Environment Variables

Create `.env` file:


### 4. Set Up Environment Variables

Create `.env` file:

```
GROQ_API_KEY=your_test_key
GH_TOKEN=your_test_token
TAVILY_API_KEY=your_test_key
```

### 5. Run Tests

```
pytest tests/ -v
```

---

## 💡 How to Contribute

### Reporting Bugs

1. Check [existing issues](https://github.com/ak-rahul/DrRepo/issues) to avoid duplicates.
2. Open a new GitHub issue using the "New Issue" button.
3. Please include the following in your issue:
   - A clear description of the bug
   - Steps to reproduce the problem
   - What you expected to happen and what actually happened
   - Details about your environment (OS, Python version, etc.)
   - Any relevant logs or screenshots


### Suggesting Features

1. Check [existing issues](https://github.com/ak-rahul/DrRepo/issues) to see if your idea is already being discussed.
2. Open a new GitHub issue and select "New Issue."
3. In your feature request, please include:
   - The problem or use case you’d like to solve
   - Your proposed solution or suggestion
   - Any alternatives you’ve considered
   - The potential benefits for users or the project


### Improving Documentation

- Fix typos, improve clarity
- Add examples
- Update outdated information
- Translate documentation

### Writing Code

1. Pick an issue or create one
2. Comment that you're working on it
3. Fork and create a branch
4. Write code and tests
5. Submit a pull request

---

## 📝 Coding Standards

### Python Style Guide

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Use [Black](https://github.com/psf/black) for formatting
- Use [isort](https://pycqa.github.io/isort/) for imports
- Use [flake8](https://flake8.pycqa.org/) for linting

### Code Formatting

Format code
```
black src/ tests/
```

Sort imports
```
isort src/ tests/
```

Lint code
```
flake8 src/ tests/
```

Type check
```
mypy src/
```


### Naming Conventions

- **Classes**: `PascalCase` (e.g., `RepoAnalyzerAgent`)
- **Functions**: `snake_case` (e.g., `analyze_repository`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`)
- **Private**: Prefix with `_` (e.g., `_internal_method`)

### Docstrings

Use Google-style docstrings:

```
def analyze_repository(repo_url: str, description: str = "") -> dict:
"""Analyze a GitHub repository.

Args:
    repo_url: GitHub repository URL
    description: Optional repository description

Returns:
    Analysis results dictionary

Raises:
    ValueError: If URL is invalid
    GithubException: If API call fails
"""
pass
```

---

## 🧪 Testing Guidelines

### Writing Tests

- Place tests in `tests/` directory
- Match source structure: `src/agents/` → `tests/test_agents/`
- Use descriptive test names: `test_repo_analyzer_handles_invalid_url`

### Test Structure

def test_feature_name():
"""Test description."""
# Arrange
```
input_data = "test"
```

# Act
```
result = function_to_test(input_data)
```

# Assert
```
assert result == expected_output
```


### Running Tests

All tests
```
pytest tests/ -v
```

Specific file
```
pytest tests/test_agents/test_repo_analyzer.py -v
```

With coverage
```
pytest tests/ --cov=src --cov-report=html
```

Integration tests only
```
pytest tests/ -m integration
```

Skip integration tests
```
pytest tests/ -m "not integration"
```


### Test Requirements

- Maintain >80% code coverage
- All tests must pass before merging
- Include both positive and negative test cases
- Mock external API calls

---

## 🔄 Pull Request Process

### 1. Create a Branch

Update main branch
```
git checkout main
git pull upstream main
```

Create feature branch
```
git checkout -b feature/your-feature-name
```

Branch naming:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation
- `test/` - Test improvements
- `refactor/` - Code refactoring

### 2. Make Changes

- Write clear, focused commits
- Follow coding standards
- Add/update tests
- Update documentation

### 3. Commit Changes

Stage changes
```
git add .
```

Commit with descriptive message
```
git commit -m "feat: add repository caching feature"
```

Commit message format:
```
<type>: <description>

[optional body]

[optional footer]
```


Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting changes
- `refactor`: Code restructuring
- `test`: Adding tests
- `chore`: Maintenance

### 4. Push to Your Fork
```
git push origin feature/your-feature-name
```

### 5. Create Pull Request

1. Go to your fork on GitHub
2. Click "New Pull Request"
3. Fill in the [PR template](.github/PULL_REQUEST_TEMPLATE.md)
4. Link related issues
5. Submit PR

### 6. Code Review

- Address review comments
- Make requested changes
- Push updates (auto-updates PR)
- Be patient and respectful

### 7. After Merge

Update main branch
```
git checkout main
git pull upstream main
```

Delete feature branch
```
git branch -d feature/your-feature-name
git push origin --delete feature/your-feature-name
```

---

## ✅ PR Checklist

Before submitting, ensure:

- [ ] Code follows style guidelines
- [ ] All tests pass (`pytest tests/`)
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commit messages follow convention
- [ ] PR description is clear
- [ ] Related issues linked
- [ ] No merge conflicts
- [ ] Pre-commit hooks pass

---

## 🎯 Good First Issues

Look for issues labeled:
- `good first issue` - Easy for newcomers
- `help wanted` - We need help
- `documentation` - Docs improvements
- `enhancement` - New features

---

## 💬 Community

### Communication

- **GitHub Issues**: Bug reports, feature requests
- **GitHub Discussions**: Questions, ideas
- **Pull Requests**: Code contributions

### Getting Help
- Check [existing issues](https://github.com/ak-rahul/DrRepo/issues)
- Ask in [Discussions](https://github.com/ak-rahul/DrRepo/discussions)

---

## 🏆 Recognition

Contributors will be:
- Mentioned in release notes
- Added to README acknowledgments

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

## 🙏 Thank You!

Your contributions make DrRepo better for everyone. We appreciate your time and effort!

---

**Questions?** Open an issue or start a discussion!

[⬆ Back to Top](#-contributing-to-drrepo)