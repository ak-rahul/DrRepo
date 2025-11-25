.PHONY: help install install-dev test lint format clean run cli docker-build docker-run

# Detect OS
ifeq ($(OS),Windows_NT)
    PYTHON := python
    RM := del /Q
    RMDIR := rmdir /S /Q
else
    PYTHON := python3
    RM := rm -f
    RMDIR := rm -rf
endif

help:
	@echo DrRepo - Makefile Commands
	@echo ==========================
	@echo install        - Install production dependencies
	@echo install-dev    - Install development dependencies
	@echo test           - Run tests
	@echo test-unit      - Run unit tests only
	@echo test-integration - Run integration tests
	@echo lint           - Run linters
	@echo format         - Format code
	@echo clean          - Clean generated files
	@echo run            - Run Streamlit app
	@echo cli            - Run CLI version
	@echo docker-build   - Build Docker image
	@echo docker-run     - Run with Docker Compose

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r requirements-dev.txt
	pre-commit install

test:
	$(PYTHON) -m pytest tests/ -v --cov=src --cov-report=html --cov-report=term

test-unit:
	$(PYTHON) -m pytest tests/ -v -m "not integration"

test-integration:
	$(PYTHON) -m pytest tests/ -v -m integration

lint:
	$(PYTHON) -m flake8 src/ tests/ --max-line-length=100
	$(PYTHON) -m pylint src/
	$(PYTHON) -m mypy src/ --ignore-missing-imports

format:
	$(PYTHON) -m black src/ tests/ app.py
	$(PYTHON) -m isort src/ tests/ app.py

format-check:
	$(PYTHON) -m black --check src/ tests/ app.py
	$(PYTHON) -m isort --check-only src/ tests/ app.py

clean:
	$(PYTHON) -m pip install --upgrade pip
ifeq ($(OS),Windows_NT)
	-@for /r %%i in (__pycache__) do @if exist "%%i" rmdir /s /q "%%i"
	-@del /s /q *.pyc 2>nul
	-@del /s /q *.pyo 2>nul
	-@if exist .pytest_cache rmdir /s /q .pytest_cache
	-@if exist .mypy_cache rmdir /s /q .mypy_cache
	-@if exist htmlcov rmdir /s /q htmlcov
	-@if exist dist rmdir /s /q dist
	-@if exist build rmdir /s /q build
	-@if exist *.egg-info rmdir /s /q *.egg-info
else
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache htmlcov dist build *.egg-info
endif
	@echo Clean complete!

run:
	$(PYTHON) -m streamlit run app.py

cli:
	@echo Enter GitHub repository URL:
	@$(PYTHON) -m src.main

docker-build:
	docker build -t drrepo:latest .

docker-run:
	docker-compose up -d

docker-stop:
	docker-compose down

docker-logs:
	docker-compose logs -f

check: format-check lint test
	@echo All checks passed!

dev-setup: install-dev
	@echo Development environment ready!

.DEFAULT_GOAL := help
