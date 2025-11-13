.PHONY: help install install-dev test lint format clean run docker-build docker-run

help:
	@echo "DrRepo - Makefile Commands"
	@echo "=========================="
	@echo "install        - Install production dependencies"
	@echo "install-dev    - Install development dependencies"
	@echo "test           - Run tests"
	@echo "lint           - Run linters"
	@echo "format         - Format code"
	@echo "clean          - Clean generated files"
	@echo "run            - Run Streamlit app"
	@echo "cli            - Run CLI version"
	@echo "docker-build   - Build Docker image"
	@echo "docker-run     - Run with Docker Compose"

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt
	pre-commit install

test:
	pytest tests/ -v --cov=src --cov-report=html

lint:
	flake8 src/ tests/
	mypy src/
	black --check src/ tests/

format:
	black src/ tests/
	isort src/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info

run:
	streamlit run app.py

cli:
	@read -p "Enter GitHub URL: " url; \
	python -m src.main $$url

docker-build:
	docker build -t drrepo:latest .

docker-run:
	docker-compose up -d

docker-stop:
	docker-compose down

docker-logs:
	docker-compose logs -f
