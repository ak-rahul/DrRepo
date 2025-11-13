# Changelog

All notable changes to DrRepo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Parallel agent execution
- Batch repository processing
- API endpoint deployment
- Custom agent configuration

---

## [1.0.0] - 2025-01-15

### 🎉 Initial Release

First stable release of DrRepo - Your Repository's Health Specialist!

### Added
- Multi-agent system with 5 specialized agents
- LangGraph workflow orchestration
- RAG-based fact checking with FAISS
- Streamlit web interface
- Command-line interface
- Quality scoring system (0-100)
- Priority action items ranking
- JSON report export
- Comprehensive documentation
- Unit and integration tests
- CI/CD with GitHub Actions
- Docker support
- Docker Compose configuration

### Agents
- 🔍 **RepoAnalyzer** - Repository structure and metadata analysis
- 🏷️ **MetadataRecommender** - Discoverability optimization
- ✍️ **ContentImprover** - README enhancement suggestions
- ✅ **ReviewerCritic** - Quality assessment and review
- 🔎 **FactChecker** - Claims verification with RAG

### Tools
- **GitHubTool** - PyGithub integration for repository data
- **RAGRetriever** - FAISS vector search with HuggingFace embeddings
- **WebSearchTool** - Tavily search for best practices
- **MarkdownTool** - README parsing and analysis

### Supported LLMs
- Groq (llama-3.3-70b-versatile) - Default, free
- OpenAI (GPT-4, GPT-3.5-turbo) - Optional

### Documentation
- Architecture guide
- API reference
- User guide
- Configuration guide
- Contributing guidelines
- Code of conduct

---

## [0.9.0] - 2025-01-10

### Added
- Beta release for testing
- Core multi-agent functionality
- Basic web interface
- CLI support

### Changed
- Improved agent prompts
- Enhanced quality scoring algorithm

### Fixed
- State management bugs
- LLM timeout issues

---

## [0.8.0] - 2025-01-05

### Added
- Fact checker agent with RAG
- FAISS integration
- HuggingFace embeddings

### Changed
- Optimized workflow execution
- Improved error handling

---

## [0.7.0] - 2025-01-01

### Added
- ReviewerCritic agent
- Quality scoring system
- Priority ranking

### Changed
- Enhanced agent coordination
- Better state management

---

## [0.6.0] - 2024-12-28

### Added
- ContentImprover agent
- Missing section detection
- Visual element recommendations

### Fixed
- README parsing edge cases

---

## [0.5.0] - 2024-12-25

### Added
- MetadataRecommender agent
- Tavily search integration
- SEO optimization suggestions

---

## [0.4.0] - 2024-12-20

### Added
- RepoAnalyzer agent
- GitHub API integration
- Markdown analysis tool

---

## [0.3.0] - 2024-12-15

### Added
- LangGraph workflow foundation
- State management system
- Base agent class

---

## [0.2.0] - 2024-12-10

### Added
- Project structure
- Configuration system
- Logging infrastructure

---

## [0.1.0] - 2024-12-05

### Added
- Initial project setup
- Basic documentation
- Development environment

---

## Release Notes Format

Each release includes:
- 🎉 **New Features** - What's new
- 🔧 **Improvements** - What's better
- 🐛 **Bug Fixes** - What's fixed
- ⚠️ **Breaking Changes** - What might break
- 📚 **Documentation** - What's documented

---

## Version Numbering

- **Major (X.0.0)**: Breaking changes
- **Minor (0.X.0)**: New features, backwards compatible
- **Patch (0.0.X)**: Bug fixes, backwards compatible

---

[Unreleased]: https://github.com/yourusername/DrRepo/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/yourusername/DrRepo/releases/tag/v1.0.0
[0.9.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.9.0
[0.8.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.8.0
[0.7.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.7.0
[0.6.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.6.0
[0.5.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.5.0
[0.4.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.4.0
[0.3.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.3.0
[0.2.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.2.0
[0.1.0]: https://github.com/yourusername/DrRepo/releases/tag/v0.1.0
