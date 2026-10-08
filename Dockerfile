FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . 
COPY schema ./schema
COPY prompts ./prompts
COPY configs ./configs
COPY app ./app
# DuckDB file is baked in (build it first: scripts/download_data.sh && python scripts/build_db.py)
COPY data/db/olist.duckdb ./data/db/olist.duckdb
ENV T2S_CONFIG=/app/configs/best.yaml
EXPOSE 8000 8501
CMD ["uvicorn", "t2s.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
