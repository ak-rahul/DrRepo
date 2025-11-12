publication-assistant/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── tests.yml
│   │   └── deploy.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── PULL_REQUEST_TEMPLATE.md
├── docs/
│   ├── architecture.md
│   ├── api_reference.md
│   ├── user_guide.md
│   ├── configuration.md
│   └── images/
│       └── workflow_diagram.png
├── src/
│   ├── __init__.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py
│   │   ├── repo_analyzer.py
│   │   ├── metadata_recommender.py
│   │   ├── content_improver.py
│   │   ├── reviewer_critic.py
│   │   └── fact_checker.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base_tool.py
│   │   ├── github_tool.py
│   │   ├── rag_retriever.py
│   │   ├── web_search_tool.py
│   │   └── markdown_tool.py
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── workflow.py
│   │   └── nodes.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── logger.py
│   │   ├── config.py
│   │   └── validators.py
│   └── main.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_agents/
│   │   ├── test_repo_analyzer.py
│   │   └── test_metadata_recommender.py
│   ├── test_tools/
│   │   ├── test_github_tool.py
│   │   └── test_web_search_tool.py
│   └── test_integration/
│       └── test_workflow.py
├── examples/
│   ├── basic_usage.py
│   ├── advanced_usage.py
│   └── sample_output.json
├── data/
│   ├── prompts/
│   │   ├── analyzer_prompts.json
│   │   └── recommender_prompts.json
│   └── templates/
│       └── readme_template.md
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── requirements.txt
├── requirements-dev.txt
├── setup.py
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── LICENSE
├── CONTRIBUTING.md
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
└── README.md
