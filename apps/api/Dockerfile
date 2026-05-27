FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY api ./api
COPY review ./review
COPY clients ./clients
COPY birds ./birds
COPY config ./config
COPY scripts ./scripts
COPY *.py ./
COPY review-dimensions.yaml model_routes.example.yaml ./

RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
