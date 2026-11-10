# --- Stage 1: build the React/Vite frontend ---
FROM node:22.23.4-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install -g npm@11.21.1
RUN npm install
# Copy only the build inputs. Copying the whole web/ directory would drag in
# node_modules — which in a git worktree is a symlink to another checkout — on
# top of the real node_modules npm just installed, and BuildKit refuses to
# replace a directory with a file.
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src/ ./src/
# Vite builds to ../truthcv/adapters/http/static per web/vite.config.ts; build in place then copy.
RUN npm run build

# --- Stage 2: python runtime serving truthcv/ + the built bundle ---
FROM python:3.11-slim AS app
WORKDIR /app

# System deps: WeasyPrint (cairo/pango/gdk-pixbuf) + pandoc for DOCX.
# libbrotli1 is listed explicitly so the CVE-2026-111497 security build (>= 1.1.0-2+deb13u1) is installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
      pandoc libbrotli1 \
      libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi-dev fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir setuptools==84.2.1 wheel==0.48.0
RUN pip install --no-cache-dir -r requirements.txt

COPY truthcv/ ./truthcv/

# Built frontend bundle from stage 1.
COPY --from=web /truthcv/adapters/http/static ./truthcv/adapters/http/static

ENV PORT=8080 DATA_DIR=/app/data
VOLUME ["/app/data"]
EXPOSE 8080

CMD ["python", "-m", "truthcv.adapters.http.main"]
