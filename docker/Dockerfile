# 书童 Shutong: web UI + API in one image. Build from the repository root:
#   docker build -f docker/Dockerfile -t shutong .
# Behind a slow or filtered network, pass mirrors, e.g.
#   --build-arg NPM_REGISTRY=https://registry.npmmirror.com --build-arg PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
# Only base images come from Docker Hub (so a daemon registry mirror covers them); no other registry is used.

FROM node:22-slim AS web
ARG NPM_REGISTRY=https://registry.npmjs.org
ENV COREPACK_NPM_REGISTRY=$NPM_REGISTRY npm_config_registry=$NPM_REGISTRY
WORKDIR /src/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim AS app
ARG PYPI_INDEX=https://pypi.org/simple
# bsdtar opens rar / 7z sources; tini reaps children and forwards signals.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libarchive-tools tini \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --index-url "$PYPI_INDEX" "uv>=0.8,<0.9"
ENV UV_DEFAULT_INDEX=$PYPI_INDEX UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/shutong ./shutong
RUN uv sync --frozen --no-dev --no-editable && rm -rf /root/.cache
COPY --from=web /src/web/dist /app/web
COPY docker/entrypoint.sh /usr/local/bin/shutong-entrypoint
RUN chmod +x /usr/local/bin/shutong-entrypoint

ENV PATH=/app/.venv/bin:$PATH \
    SHUTONG_DATA=/config \
    SHUTONG_WEB=/app/web \
    SHUTONG_HOST=0.0.0.0 \
    SHUTONG_PORT=8899 \
    TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1
EXPOSE 8899
VOLUME /config
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/auth/status' % os.environ['SHUTONG_PORT'], timeout=4)"
ENTRYPOINT ["tini", "--", "shutong-entrypoint"]
