# One image for both the API and the Celery worker (different start commands).
# Phase 8 turns this into a slimmer multi-stage production build.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OCR system packages: Tesseract (OCR engine + English data) and Poppler (PDF -> image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies BEFORE copying the code. Docker caches each layer, so editing
# code doesn't trigger a slow reinstall; only changing pyproject.toml does.
# (A stub package satisfies `pip install .`; the project itself is then removed and
# the real code is used from /app via PYTHONPATH.)
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y invoiceiq \
    && rm -rf app build *.egg-info

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Never run as root: a compromised process then can't modify the system.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# --proxy-headers: trust X-Forwarded-For from the reverse proxy, so rate limiting
# sees the real client IP instead of the proxy's.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
