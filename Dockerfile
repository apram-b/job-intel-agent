FROM python:3.12.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY job_intel ./job_intel
COPY migrations ./migrations
COPY alembic.ini app.py main.py ./
RUN uv sync --locked --no-dev && useradd --uid 10001 --create-home jobintel && mkdir -p /app/data && chown jobintel /app/data
USER jobintel
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "job_intel.v2.cli"]
CMD ["worker"]
