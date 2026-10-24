FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models KNOWRA_DB=/data/knowra.db
WORKDIR /code
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-semantic.txt ./
ARG INSTALL_SEMANTIC=true
RUN pip install --no-cache-dir -r requirements.txt && if [ "$INSTALL_SEMANTIC" = "true" ]; then pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements-semantic.txt; fi
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN if [ "$INSTALL_SEMANTIC" = "true" ]; then python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('$EMBEDDING_MODEL')"; fi
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --uid 10001 --create-home knowra && mkdir -p /data /models && chown -R knowra:knowra /data /models
USER knowra
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
