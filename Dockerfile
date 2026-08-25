# --- Stage 1: build the React/Vite frontend ---
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
# Copy only the build inputs. Copying the whole web/ directory would drag in
# node_modules — which in a git worktree is a symlink to another checkout — on
# top of the real node_modules npm just installed, and BuildKit refuses to
# replace a directory with a file.
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src/ ./src/
# Vite builds to ../api/static per web/vite.config.ts; build in place then copy.
RUN npm run build

# --- Stage 2: python runtime serving api/ + the built bundle ---
FROM python:3.11-slim AS app
WORKDIR /app

# System deps: WeasyPrint (cairo/pango/gdk-pixbuf) + pandoc for DOCX.
RUN apt-get update && apt-get install -y --no-install-recommends \
      pandoc \
      libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi-dev fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Shared single-module helper, not a package — the stores import it, so it must
# be copied explicitly like the packages below.
COPY datafile.py ./
COPY secretstore/ ./secretstore/
COPY prompts/ ./prompts/
COPY providers/ ./providers/
COPY truth/ ./truth/
COPY tailor/ ./tailor/
COPY guardrail/ ./guardrail/
COPY render/ ./render/
COPY coverletter/ ./coverletter/
COPY applications/ ./applications/
COPY screening/ ./screening/
COPY agentconfig/ ./agentconfig/
COPY companyboards/ ./companyboards/
COPY connections/ ./connections/
COPY modelrouting/ ./modelrouting/
COPY agenttools/ ./agenttools/
COPY api/ ./api/

# Built frontend bundle from stage 1.
COPY --from=web /api/static ./api/static

ENV PORT=8080 DATA_DIR=/app/data
VOLUME ["/app/data"]
EXPOSE 8080

CMD ["python", "-m", "api.main"]
