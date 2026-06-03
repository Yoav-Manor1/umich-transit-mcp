# Container image for the U-Mich Transit poller (24/7 data collection).
# The MCP server can also be run from this image, but the poller is the
# long-running process meant for deployment.
FROM python:3.11-slim

# uv for fast, reproducible installs (pinned via uv.lock).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies first (cached layer; only re-runs when deps change).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

# Copy the application and install the project itself.
COPY . .
RUN uv sync --frozen

ENTRYPOINT ["sh", "deploy/entrypoint.sh"]
