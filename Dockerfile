# krystal-curator — headless monitor image (TUI also works: docker run -it ... krystal-curator)
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim-bookworm
RUN useradd --create-home --uid 1000 curator
WORKDIR /app
COPY --from=build --chown=curator:curator /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    KRYSTAL_DATA_DIR=/data \
    KRYSTAL_CONFIG=/config/config.toml \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data /config /app/reports && chown -R curator:curator /data /config /app
USER curator
VOLUME ["/data", "/config", "/app/reports"]
HEALTHCHECK --interval=5m --timeout=20s --start-period=2m \
  CMD krystal-curator status | grep -q "(alive)" || exit 1
ENTRYPOINT ["krystal-curator"]
CMD ["watch"]
