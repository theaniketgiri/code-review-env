# Use an optimized Python 3.12 slim image
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /bin/uv

# Copy definition files first for layer caching
COPY pyproject.toml uv.lock ./

# Copy application source
COPY . .

# Install dependencies
RUN uv sync --frozen

# Set environment variables for OpenEnv runtime
ENV PYTHONPATH=/app
ENV ENABLE_WEB_INTERFACE=true

# Expose the default OpenEnv port
EXPOSE 8000

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start the uvicorn server
CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
