FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RUNNER_SECRET_FILE=/secret/runner.key

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY runner.py .

# same uid as the AXoR container, so both can read the shared secret file; the Docker socket's group is added at run time
RUN useradd --create-home --uid 1000 runner && mkdir -p /secret && chown runner /secret
USER runner
VOLUME ["/secret"]
EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8200/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "runner:app", "--host", "0.0.0.0", "--port", "8200"]
