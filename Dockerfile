FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency installation
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY agentchaos/ agentchaos/

# Install the package and all extras in a single layer
RUN uv sync --locked --no-dev

# Results land here; mount a volume to persist them
VOLUME /app/results

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["agentchaos"]
CMD ["--help"]
