# Multi-stage build. Used for local docker compose AND production (API + worker).
#
#   Stage 1 (builder): install Python dependencies into a virtualenv. Needs pip
#                      and build caches, none of which belong in the final image.
#   Stage 2 (runtime): slim image with only the virtualenv, OCR system packages
#                      and our code. Smaller, faster to pull, less attack surface.

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
# Dependencies before code: Docker caches this layer, so code edits don't trigger a
# reinstall. A stub package satisfies `pip install .`; the project itself is then
# uninstalled and the real code is copied in the runtime stage.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y invoiceiq

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/opt/venv/bin:$PATH

# OCR system packages: Tesseract (OCR engine + English data) and Poppler (PDF -> image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Never run as root: a compromised process then can't modify the system.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1

# --proxy-headers: trust X-Forwarded-For from the load balancer so rate limiting sees
# the real client IP. Worker count comes from WEB_CONCURRENCY (uvicorn reads it).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
