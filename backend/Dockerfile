FROM python:3.12-slim

WORKDIR /app

# Playwright/Crawl4AI system dependencies + Tesseract OCR for image-based PDFs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Create appuser FIRST so Playwright installs to its home (not root)
RUN useradd -m -u 1000 appuser && mkdir -p /home/appuser/.cache && chown -R appuser:appuser /home/appuser

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium:
#  - system deps as root (libnspr4, libnss3, etc.)
#  - browser binary as appuser (so the browsers live in its writable cache)
RUN playwright install-deps chromium
USER appuser
RUN playwright install chromium
USER root

COPY --chown=appuser:appuser backend/app ./app
RUN mkdir -p /app/cache/content_hashes && chown -R appuser:appuser /app/cache

USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
