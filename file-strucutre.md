DrRepo/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── tests.yml
│   │   └── deploy.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── PULL_REQUEST_TEMPLATE.md
│
├── docs/
│   ├── architecture.md
│   ├── api_reference.md
│   ├── user_guide.md
│   ├── configuration.md
│   └── images/
│       └── workflow_diagram.png
│
├── src/
│   ├── __init__.py                    # Project initialization
│   ├── main.py                        # Main application entry
│   │
│   ├── agents/                        # 5 AI Agents
│   │   ├── __init__.py
│   │   ├── base_agent.py              # Base agent class (Groq/OpenAI support)
│   │   ├── repo_analyzer.py           # Repository data analyzer
│   │   ├── metadata_recommender.py    # Metadata optimization
│   │   ├── content_improver.py        # README enhancement (FIXED)
│   │   ├── reviewer_critic.py         # Quality assessment
│   │   └── fact_checker.py            # RAG-based verification (FIXED)
│   │
│   ├── tools/                         # Tool integrations
│   │   ├── __init__.py
│   │   ├── github_tool.py             # GitHub API integration
│   │   ├── rag_retriever.py           # FAISS + HuggingFace embeddings
│   │   ├── web_search_tool.py         # Tavily search
│   │   └── markdown_tool.py           # README parsing & analysis
│   │
│   ├── graph/                         # LangGraph workflow
│   │   ├── __init__.py
│   │   ├── state.py                   # State management
│   │   └── workflow.py                # Multi-agent orchestration
│   │
│   └── utils/                         # Utilities
│       ├── __init__.py
│       ├── config.py                  # Configuration (Groq support)
│       └── logger.py                  # Logging system
│
├── tests/                             # Unit tests
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
│
├── examples/                          # Usage examples
│   ├── basic_usage.py
│   ├── advanced_usage.py
│   └── sample_output.json
│
├── reports/                           # ✅ Generated analysis outputs
│   └── requests_report.json
│
├── logs/                              # ✅ Application logs
│   └── app.log
│
├── venv/                              # ✅ Virtual environment
│   └── (Python packages)
│
├── app.py                             # ✅ Streamlit frontend (WORKING)
├── gradio_app.py                      # Optional: Gradio interface
│
├── .env                               # ✅ API keys (YOUR CONFIG)
├── .env.example                       # Example environment file
├── .gitignore                         # Git ignore rules
├── requirements.txt                   # ✅ Production dependencies (Groq, Streamlit)
├── requirements-dev.txt               # ✅ Development dependencies
├── requirements-minimal.txt           # Minimal dependencies backup
│
├── setup.py                           # Package setup
├── pyproject.toml                     # Modern Python config
├── Dockerfile                         # Docker containerization
├── docker-compose.yml                 # Docker compose config
├── Makefile                           # Build automation
│
├── LICENSE                            # Project license
├── CONTRIBUTING.md                    # Contribution guidelines
├── CHANGELOG.md                       # Version history
├── CODE_OF_CONDUCT.md                 # Community guidelines
└── README.md                          # 🩺 DrRepo Documentation
