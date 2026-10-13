# Built in Azure with `az acr build` (no local Docker needed). Tesseract is included so the
# offline engine works inside a firewall and as the cloud engine's cross-check and fallback.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # One OpenMP thread per Tesseract call: concurrency comes from parallel requests.
    OMP_THREAD_LIMIT=1 \
    # Listen port; set PORT to match an existing ingress target port instead of changing ingress.
    PORT=8000

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.lock ./
RUN pip install -r requirements.lock
COPY app ./app
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=2).status == 200 else 1)"
CMD ["sh", "-c", "exec uvicorn app.api.main:app --host 0.0.0.0 --port \"$PORT\" --workers 1 --no-server-header"]
