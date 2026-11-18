FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DNS_DATA=/data \
    DNS_SECRET_FILE=/secret/dns.key

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY dns.py .

# same uid as the AXoR container, so both can read the shared secret file; DNS itself listens on 5353 (no privileges)
RUN useradd --create-home --uid 1000 dns && mkdir -p /data /secret && chown dns /data /secret
USER dns
VOLUME ["/data", "/secret"]
EXPOSE 5353/udp 5353/tcp 8400

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8400/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "dns:app", "--host", "0.0.0.0", "--port", "8400"]
