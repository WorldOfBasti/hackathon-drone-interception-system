#!/bin/bash
set -e

echo "=== OpenTAKServer Docker Entrypoint ==="

echo "Waiting for RabbitMQ..."
for i in $(seq 1 30); do
    if nc -z rabbitmq 5672 2>/dev/null; then
        echo "RabbitMQ is ready"
        break
    fi
    echo "  attempt $i/30..."
    sleep 2
done

echo "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if nc -z postgres 5432 2>/dev/null; then
        echo "PostgreSQL is ready"
        break
    fi
    echo "  attempt $i/30..."
    sleep 2
done

mkdir -p /etc/opentakserver/certs /var/lib/opentakserver /var/log/opentakserver

for required_var in TAK_SECRET_KEY TAK_SECURITY_PASSWORD_SALT TAK_POSTGRES_PASSWORD TAK_RABBITMQ_PASSWORD; do
    if [ -z "${!required_var:-}" ]; then
        echo "Missing required environment variable: $required_var" >&2
        exit 1
    fi
done

# Auto-generate self-signed certs if none exist
if [ ! -f /etc/opentakserver/certs/server.crt ]; then
    echo "Generating self-signed certificates..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:4096 \
        -keyout /etc/opentakserver/certs/server.key \
        -out /etc/opentakserver/certs/server.crt \
        -subj "/CN=tak.dronedefense.local/O=DroneDefense/OU=TAK"
    cp /etc/opentakserver/certs/server.crt /etc/opentakserver/certs/ca.crt
    echo "Certificates generated"
fi

python3 - <<'PY'
from pathlib import Path
import os

config = Path("/etc/opentakserver/config.yml.reference").read_text()
for key in (
    "TAK_SECRET_KEY",
    "TAK_SECURITY_PASSWORD_SALT",
    "TAK_POSTGRES_PASSWORD",
    "TAK_RABBITMQ_PASSWORD",
):
    config = config.replace("${" + key + "}", os.environ[key])
Path("/var/lib/opentakserver/config.yml").write_text(config)
PY

if [ "$#" -eq 0 ]; then
    set -- python3 /usr/local/lib/python3.11/site-packages/opentakserver/serve_ui.py
fi

echo "Starting $*..."
exec "$@"
