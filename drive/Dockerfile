FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DRIVE_DATA=/data \
    DRIVE_SECRET_FILE=/secret/drive.key

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY drive.py .

# same uid as the Scout container, so both can read the shared secret file
RUN useradd --create-home --uid 1000 drive && mkdir -p /data /secret && chown drive /data /secret
USER drive
VOLUME ["/data", "/secret"]
EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "drive:app", "--host", "0.0.0.0", "--port", "8100"]
