FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PUSH_DATA=/data \
    PUSH_SECRET_FILE=/secret/push.key

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY push.py .

# same uid as the AXoR container, so both can read the shared secret file
RUN useradd --create-home --uid 1000 push && mkdir -p /data /secret && chown push /data /secret
USER push
VOLUME ["/data", "/secret"]
EXPOSE 8300

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8300/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "push:app", "--host", "0.0.0.0", "--port", "8300"]
