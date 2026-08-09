FROM python:3.11-slim

ARG APP_VERSION=dev

WORKDIR /app
COPY pyproject.toml README.md /app/
RUN mkdir -p /app/pretalx_speakerops \
    && printf '__version__ = "0.0.0"\n' > /app/pretalx_speakerops/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf /app/pretalx_speakerops
COPY pretalx_speakerops /app/pretalx_speakerops
COPY mock_accelevents /app/mock_accelevents
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN pip install --no-cache-dir --no-deps . \
    && chmod +x /app/docker/entrypoint.sh
COPY docker/pretalx.cfg /app/docker/pretalx.cfg

ENV PRETALX_CONFIG_FILE=/app/docker/pretalx.cfg
ENV APP_VERSION=${APP_VERSION}
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
