.PHONY: install dev test lint clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
