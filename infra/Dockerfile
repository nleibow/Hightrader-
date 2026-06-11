FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY scripts ./scripts

# Default: run the research pipeline. Override CMD for live trading.
CMD ["python", "scripts/run_pipeline.py"]
