.PHONY: help install dev-install test lint format clean docker-up docker-down docker-logs db-init

help:
	@echo "Available commands:"
	@echo "  make install      - Install production dependencies"
	@echo "  make dev-install  - Install development dependencies"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linters (ruff, mypy)"
	@echo "  make format       - Format code with black"
	@echo "  make clean        - Clean up generated files"
	@echo "  make docker-up    - Start Docker services"
	@echo "  make docker-down  - Stop Docker services"
	@echo "  make docker-logs  - View Docker logs"
	@echo "  make db-init      - Initialize database"

install:
	pip install -e .

dev-install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --cov=app --cov-report=html

lint:
	ruff check src tests
	mypy src

format:
	black src tests
	ruff check --fix src tests

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build dist .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-build:
	docker-compose build

db-init:
	python -c "from app.core.database import init_db; init_db()"

# Development shortcuts
dev: docker-up
	@echo "Services started. API: http://localhost:8000, Flower: http://localhost:5555"

run-api:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run-worker:
	celery -A app.tasks.celery_app:celery_app worker --loglevel=info

run-flower:
	celery -A app.tasks.celery_app:celery_app flower --port=5555
