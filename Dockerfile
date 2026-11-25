# The Disease Division's API: the librarian behind one endpoint. docker compose builds and runs it
# (see docker-compose.yml). The Anthropic key reaches the container from .env when it starts; it
# is never copied into the image (.dockerignore keeps .env out of the build).
FROM python:3.12-slim

# uv at the version that wrote uv.lock, so `uv sync --locked` installs exactly what CI tests.
RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    FASTEMBED_CACHE_PATH=/app/models

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev
COPY kb ./kb

# Download the embedding model now (about 65 MB), so the running server never fetches anything.
RUN uv run --no-sync python -c "from fastembed import TextEmbedding; from disease_division.embed import MODEL, cache_dir; TextEmbedding(MODEL, cache_dir=cache_dir())"

# Answer as an ordinary user, not as root.
RUN useradd --create-home librarian && chown -R librarian /app
USER librarian

EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=4)"]
CMD ["uv", "run", "--no-sync", "division", "serve", "--host", "0.0.0.0", "--port", "8002"]
