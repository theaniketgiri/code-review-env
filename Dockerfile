# Use an optimized Python 3.12 slim image
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /bin/uv

# Copy definition files first to leverage Docker cache
COPY pyproject.toml uv.lock ./

# Install python dependencies natively
RUN uv sync --frozen

# Copy the rest of the application files
COPY . .

# Set environment variables for OpenEnv runtime
ENV PYTHONPATH=/app
ENV ENABLE_WEB_INTERFACE=true

# Expose the default OpenEnv port matching the README.md
EXPOSE 8000

# Start the uvicorn server serving the Custom Gradio Dashboard securely
CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
