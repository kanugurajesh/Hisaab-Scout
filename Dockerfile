FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY data ./data
RUN uv sync --frozen

RUN useradd --create-home scout
USER scout

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "/app/.venv/bin/uvicorn scout.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
