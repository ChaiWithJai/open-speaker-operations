FROM python:3.11-slim AS python-deps

WORKDIR /app
COPY pyproject.toml README.md /app/
RUN mkdir -p /app/pretalx_speakerops \
    && printf '__version__ = "0.0.0"\n' > /app/pretalx_speakerops/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf /app/pretalx_speakerops

FROM node:22-slim AS schedule-assets

WORKDIR /build
COPY --from=python-deps /usr/local/lib/python3.11/site-packages/pretalx/frontend/schedule-editor/ /build/
RUN npm ci \
    && OUT_DIR=/schedule-static BASE_URL=/static/ npm run build

FROM python-deps

ARG APP_VERSION=dev

WORKDIR /app
COPY pretalx_speakerops /app/pretalx_speakerops
COPY mock_accelevents /app/mock_accelevents
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
COPY --from=schedule-assets /schedule-static /app/schedule-static
RUN pip install --no-cache-dir --no-deps . \
    && chmod +x /app/docker/entrypoint.sh
COPY docker/pretalx.cfg /app/docker/pretalx.cfg

ENV PRETALX_CONFIG_FILE=/app/docker/pretalx.cfg
ENV APP_VERSION=${APP_VERSION}
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
