FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/loom

COPY apps/chronicle/persistence/requirements.txt /tmp/chronicle-persistence-requirements.txt
COPY apps/chronicle/read_api/requirements.txt /tmp/chronicle-read-api-requirements.txt

RUN python3 -m pip install --no-cache-dir \
      -r /tmp/chronicle-persistence-requirements.txt \
      -r /tmp/chronicle-read-api-requirements.txt \
    && groupadd --system --gid 10001 chronicle \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin chronicle

COPY --chown=chronicle:chronicle apps/chronicle ./apps/chronicle

USER chronicle

EXPOSE 8080

CMD ["python3", "apps/chronicle/read_api/server.py", "--host", "0.0.0.0", "--port", "8080"]
