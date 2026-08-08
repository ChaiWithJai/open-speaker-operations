FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY pretalx_speakerops /app/pretalx_speakerops
COPY mock_accelevents /app/mock_accelevents
RUN pip install --no-cache-dir ".[dev]" celery redis psycopg[binary] Faker freezegun
COPY docker/pretalx.cfg /app/docker/pretalx.cfg

ENV PRETALX_CONFIG_FILE=/app/docker/pretalx.cfg
EXPOSE 8000
CMD ["python", "-m", "pretalx", "runserver", "0.0.0.0:8000", "--noreload"]
