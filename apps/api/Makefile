.PHONY: help install dev test compile clean

help:
	@echo "Pecker public API commands:"
	@echo "  make install   Install editable backend dependencies"
	@echo "  make dev       Run FastAPI on 127.0.0.1:8000"
	@echo "  make test      Run public smoke tests"
	@echo "  make compile   Compile Python modules"
	@echo "  make clean     Remove local caches"

install:
	python -m pip install -e ".[dev]"

dev:
	uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

test:
	python -m pytest -q

compile:
	python -m compileall -q .

clean:
	python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; shutil.rmtree('.pytest_cache', ignore_errors=True)"
