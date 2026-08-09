FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY pretalx_speakerops /app/pretalx_speakerops
COPY mock_accelevents /app/mock_accelevents
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN pip install --no-cache-dir ".[dev]" celery redis psycopg[binary] Faker freezegun
RUN chmod +x /app/docker/entrypoint.sh
COPY docker/pretalx.cfg /app/docker/pretalx.cfg

ENV PRETALX_CONFIG_FILE=/app/docker/pretalx.cfg
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
