"""Setup configuration for DrRepo package."""
from setuptools import setup, find_packages
from pathlib import Path

# Read README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

setup(
    name="drrepo",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Multi-agent AI system for GitHub repository analysis",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/DrRepo",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Quality Assurance",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.9",
    install_requires=[
        "langgraph>=0.2.28",
        "langchain>=0.3.0",
        "langchain-core>=0.3.0",
        "langchain-community>=0.3.0",
        "langchain-openai>=0.2.1",
        "groq>=0.9.0",
        "langchain-groq>=0.2.0",
        "PyGithub>=2.1.1",
        "tavily-python>=0.5.0",
        "faiss-cpu>=1.8.0",
        "sentence-transformers>=2.2.0",
        "python-dotenv>=1.0.0",
        "requests>=2.31.0",
        "tiktoken>=0.7.0",
        "pydantic>=2.8.2",
        "streamlit>=1.31.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.3.2",
            "pytest-cov>=5.0.0",
            "black>=24.8.0",
            "flake8>=7.1.0",
            "isort>=5.13.2",
            "mypy>=1.11.1",
            "pre-commit>=3.8.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "drrepo=src.main:main",
        ],
    },
)
