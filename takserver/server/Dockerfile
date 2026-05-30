FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.description="OpenTAKServer – Drone Defense TAK Server"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV OTS_DATA_FOLDER=/var/lib/opentakserver

RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-openbsd \
    openssl \
    ffmpeg \
    curl \
    ca-certificates \
    gcc \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY scripts/patch_opentakserver.py /tmp/patch_opentakserver.py
RUN python /tmp/patch_opentakserver.py && rm /tmp/patch_opentakserver.py

COPY config/config.yml /var/lib/opentakserver/config.yml
COPY config/config.yml /etc/opentakserver/config.yml.reference
COPY scripts/serve_ui.py /usr/local/lib/python3.11/site-packages/opentakserver/serve_ui.py
COPY frontend /usr/local/lib/python3.11/site-packages/opentakserver/frontend
COPY scripts/docker_entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /etc/opentakserver/certs /var/lib/opentakserver /var/log/opentakserver

EXPOSE 8088 8089 8443 8554 8889 9997

VOLUME ["/etc/opentakserver/certs", "/var/lib/opentakserver", "/var/log/opentakserver"]

ENTRYPOINT ["/entrypoint.sh"]
