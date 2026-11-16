# Norn in one image: the Python server, the web UI, go2rtc and FFmpeg.
# Build: docker build -t norn .   Run: see compose.yaml.

# 1. The web UI.
FROM node:24-alpine AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. The Python package, with the web UI inside it, in a virtual environment.
FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
COPY --from=web /src/build ./src/norn/web
RUN uv sync --locked --no-dev --no-editable

# 3. The runtime.
FROM python:3.13-slim
ARG TARGETARCH
ARG GO2RTC_VERSION=1.9.15
# tzdata: TZ sets the local time of the recordings' file names.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
ADD --chmod=755 https://github.com/AlexxIT/go2rtc/releases/download/v${GO2RTC_VERSION}/go2rtc_linux_${TARGETARCH} /usr/local/bin/go2rtc
COPY --from=mwader/static-ffmpeg:9.0.2 /ffmpeg /ffprobe /usr/local/bin/
COPY --from=app /app/.venv /app/.venv

ENV PATH=/app/.venv/bin:$PATH \
    NORN_CONFIG=/config/config.yaml \
    NORN_RECORDINGS=/recordings \
    NORN_TEMP=/temp \
    PYTHONUNBUFFERED=1

VOLUME ["/config", "/recordings", "/temp"]
# 8000: web UI and API. 8555: WebRTC media (TCP and UDP).
EXPOSE 8000 8555/tcp 8555/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["norn"]
