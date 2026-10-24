# syntax=docker/dockerfile:1
#
# ai-reader-2 in a container. Replaces the 1.0.0 image, which was built from
# ai-reader (reader3's parser and ebooklib, `book.pkl` books) — see README.md,
# "Docker". Here the EPUB format is epubx's job, and the book is the EPUB.
#
# Build for this machine:
#   docker build -t taylorren/epub-ai-reader:2.0.0 .
# Build both platforms and publish (needs a buildx builder with arm64 binfmt):
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     -t taylorren/epub-ai-reader:2.0.0 -t taylorren/epub-ai-reader:latest --push .
#
# The container keeps the interface the old image had — port 8123, uid 1000,
# /app/books for the library, /data for the database, the same OLLAMA_* and
# READER_* variables — so an existing deployment directory keeps working.
# What changed inside: the book is stored as the EPUB itself
# (books/<slug>/<slug>.epub, BASE_DIR/books from routers/app_state.py), so the
# books volume needs a re-upload rather than the old `*_data/book.pkl` folders.

FROM python:3.12-slim-bookworm AS builder

# A build behind a proxy passes these in (nothing here bakes one in):
#   docker build --build-arg HTTPS_PROXY=http://proxy.example:3128 .
ARG HTTP_PROXY
ARG HTTPS_PROXY

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer: only the lock files, so this is cached until deps change.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim-bookworm AS runtime

# READER_DB is set explicitly: `routers/app_state.py` defaults it to
# BASE_DIR/reader_data.db, which is inside the image and would be lost on every
# rebuild. The database belongs in the mounted volume.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    READER_HOST=0.0.0.0 \
    READER_PORT=8123 \
    READER_DB=/data/reader_data.db

ARG VCS_REF=""
ARG BUILD_DATE=""

LABEL org.opencontainers.image.title="ePub AI Reader" \
      org.opencontainers.image.description="Self-hosted EPUB reader with AI-assisted annotation. Renders the publisher's own EPUB on epubx (no reader3 parser, no ebooklib); annotations live in SQLite." \
      org.opencontainers.image.url="https://github.com/taylorren/ai-reader-2" \
      org.opencontainers.image.source="https://github.com/taylorren/ai-reader-2" \
      org.opencontainers.image.documentation="https://github.com/taylorren/ai-reader-2#readme" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Taylor Ren" \
      org.opencontainers.image.base.name="docker.io/library/python:3.12-slim-bookworm" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# uid/gid 1000 matches the NAS `tr` account so bind mounts are writable.
RUN groupadd --gid 1000 reader \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin reader

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY server.py booksource.py database.py ai_service.py ./
COPY routers/ ./routers/
COPY templates/ ./templates/
COPY static/ ./static/

# The README and the licence travel with the image: the registry page's
# description can be taken from the README verbatim, and MIT's notice travels
# with the copy of the software that a pulled image is.
COPY README.md LICENSE ./

# Both writable paths are under /app, not under /data: an upload stages into
# BASE_DIR/temp and the book lands in BASE_DIR/books. /data only holds the
# database and SQLite's -wal/-shm companions.
RUN mkdir -p /app/temp /app/books /data \
    && chown -R reader:reader /app /data

USER reader

EXPOSE 8123

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8123/', timeout=4).status==200 else 1)"]

CMD ["python", "/app/server.py"]
