# Image du serveur Aide Culinaire. Construction depuis la racine du dépôt :
#   docker compose -f deploiement/compose.yaml build
FROM node:22-bookworm-slim AS pwa
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.15-slim-bookworm
# Version du CLI figée (X-6) : la mise à jour se fait en changeant cette ligne et en reconstruisant l'image.
ARG CLAUDE_CODE_VERSION=2.1.322
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Node 22 repris de l'image officielle : le CLI Claude et le parseur Cooklang (WASM) en dépendent.
COPY --from=pwa /usr/local/bin/node /usr/local/bin/node
COPY --from=pwa /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# hadolint ignore=DL3008,DL3016
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git openssh-client rclone sqlite3 \
        poppler-utils tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

RUN useradd --create-home --uid 1000 cuisine
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/
RUN uv sync --project backend --frozen --no-dev --no-install-project
COPY backend/outils/package.json backend/outils/package-lock.json backend/outils/
RUN npm ci --prefix backend/outils --omit=dev
COPY backend/ backend/
COPY agent/ agent/
COPY --from=pwa /src/frontend/dist frontend/dist

USER cuisine
WORKDIR /app/backend
ENV AC_RACINE=/srv/aide-culinaire AC_HOTE=0.0.0.0 AC_PORT=8000 \
    PATH="/app/backend/.venv/bin:${PATH}"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8000/api/session || exit 1
CMD ["python", "-m", "app"]
