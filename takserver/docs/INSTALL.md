# OpenTAKServer – Drone Defense Installation Guide

## Overview

This document covers installation of the Drone Defense TAK Server (OpenTAKServer) on **Windows** and **macOS**.

## Required GitHub Repositories

| Repository | URL | Purpose |
|-----------|-----|---------|
| takserver | `https://github.com/Hackathon418-2/takserver.git` | Main server: Docker Compose config, OTS backend, client configs, tools |
| OpenTAKServer-UI | `https://github.com/brian7704/OpenTAKServer-UI` | WebUI frontend (React SPA, v1.7.5 tag) — `tools/e2e_test.py` can clone/build this automatically |

```bash
git clone https://github.com/Hackathon418-2/takserver.git
cd takserver
python3 tools/e2e_test.py
```

## Architecture (Docker)

```
┌──────────────────────────────────────────────────────────┐
│                   TAK Drone Defense Server               │
│                                                          │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ OpenTAKServer │  │ RabbitMQ │  │   PostgreSQL     │  │
│  │ (Web/API)     │  │(Message Q)│  │   (Database)     │  │
│  └──────┬────────┘  └────┬─────┘  └────────┬─────────┘  │
│         │                │                  │            │
│    Port 8089 (WebUI)  Port 5672        Port 5432        │
│    Port 8088 (CoT TCP)                                   │
│    Port 8443 (CoT SSL)                                   │
└──────────────────────────────────────────────────────────┘
         ▲
         │            Clients
    ┌────┴────┐                    ┌────┴────┐
    │ WinTAK  │                    │  iTAK   │
    │Windows  │                    │  iOS    │
    └─────────┘                    └─────────┘
```

## Prerequisites

| Component | Minimum Version |
|-----------|----------------|
| Python    | 3.8+           |
| RAM       | 4 GB           |
| Disk      | 2 GB free      |
| OS        | Windows 10+ / macOS 12+ |

---

## Windows Installation

### Quick Install

1. **Open PowerShell as Administrator**  
   Right-click PowerShell -> Run as Administrator

2. **Navigate to the repository**
   ```powershell
   cd takserver\server\scripts
   ```

3. **Run the installer**
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\windows_install.ps1
   ```

### Step-by-Step

The installer performs these steps automatically:

1. ✅ Checks Administrator privileges
2. ✅ Verifies Python 3.8+ is installed
3. ✅ Installs OpenTAKServer via pip
4. ✅ Installs RabbitMQ message broker
5. ✅ Installs MediaMTX for video streaming
6. ✅ Copies configuration to `%ProgramData%\OpenTAKServer\config.yml`
7. ✅ Creates Windows Service `OpenTAKServer`
8. ✅ Configures Windows Firewall rules

### Installer Options

| Flag | Description |
|------|-------------|
| `--SkipPython` | Skip Python verification |
| `--SkipRabbitMQ` | Skip RabbitMQ installation |
| `--SkipMediaMTX` | Skip MediaMTX installation |
| `--SkipService` | Skip Windows Service creation |

### Manual Python Installation

If Python is not installed:
1. Download Python 3.8+ from https://www.python.org/downloads/
2. Check "Add Python to PATH" during installation
3. Re-run the installer

### Post-Installation

```powershell
# Check service status
Get-Service -Name OpenTAKServer

# Start/Stop service
Start-Service -Name OpenTAKServer
Stop-Service -Name OpenTAKServer

# View logs
Get-EventLog -LogName Application -Source OpenTAKServer -Newest 20
```

### Access Points

| Service | URL |
|---------|-----|
| Web UI | http://localhost:8089 |
| CoT TCP | tcp://localhost:8088 |
| CoT SSL | ssl://localhost:8443 |
| RTSP Stream | rtsp://localhost:8554 |
| MediaMTX API | http://localhost:9997 |
| RabbitMQ Mgmt | http://localhost:15672 |

---

## macOS Installation

### Quick Install

```bash
cd takserver/server/scripts
chmod +x macos_install.sh
./macos_install.sh
```

### Step-by-Step

The installer performs these steps:

1. ✅ Checks macOS 12+ (Monterey)
2. ✅ Installs Homebrew (if needed)
3. ✅ Installs Python 3.11 via Homebrew
4. ✅ Installs OpenTAKServer via pip
5. ✅ Installs RabbitMQ via Homebrew
6. ✅ Installs MediaMTX (binary download)
7. ✅ Creates directory structure
8. ✅ Sets up `_opentakserver` service user
9. ✅ Copies config to `/usr/local/var/opentakserver/config.yml`
10. ✅ Creates launchd daemon

### Installer Options

| Flag | Description |
|------|-------------|
| `--skip-python` | Skip Python check/install |
| `--skip-rabbitmq` | Skip RabbitMQ |
| `--skip-mediamtx` | Skip MediaMTX |
| `--skip-launchd` | Skip daemon setup |

### Service Management

```bash
# Start the server
sudo launchctl kickstart system/org.opentakserver.ots

# Stop the server
sudo launchctl bootout system/org.opentakserver.ots

# Check status
sudo launchctl print system/org.opentakserver.ots

# View logs
tail -f /usr/local/var/log/opentakserver/ots-out.log
tail -f /usr/local/var/log/opentakserver/ots-err.log
```

---

## Certificate Setup

Generate certificates using the included tool:

```bash
cd tools/cert_gen
python generate_certs.py --output ./certs --server-name tak.dronedefense.local
```

This creates:
- `ca.crt` / `ca.key` – Certificate Authority
- `server.crt` / `server.key` – Server certificate
- `client.crt` / `client.key` – Client certificate
- `client.p12` – Client bundle (for WinTAK/iTAK import)

Update `server/config/config.yml` with the certificate paths:

```yaml
OTS_SSL_CERT: "/path/to/server.crt"
OTS_SSL_KEY:  "/path/to/server.key"
OTS_CA_CERT:  "/path/to/ca.crt"
```

---

## Client Configuration

### WinTAK (Windows)

1. Install WinTAK from the official source
2. Import `client.p12` certificate (password: `takserver`)
3. Import `server_config.pref` Data Package from `clients/wintak/`
4. Or manually configure:
   - Server: `tak.dronedefense.local`
   - Port: `8088` for TCP or `8443` for SSL
   - Use the client certificate for authentication

### iTAK (iOS)

1. Install iTAK from the App Store
2. Import `client.p12` certificate
3. Add server connection:
   - Address: `tak.dronedefense.local`
   - Port: `8443`
   - SSL: Enabled
4. Select the imported client certificate

---

## Docker Deployment

### Prerequisites

- Docker Engine 24+
- Docker Compose v2+
- Node.js 22+ & npm (to build the WebUI)
- Git

### Quick Start

```powershell
# 1. Clone both repos
git clone https://github.com/Hackathon418-2/takserver.git
git clone https://github.com/brian7704/OpenTAKServer-UI

# 2. Build the WebUI
cd OpenTAKServer-UI
npm install
npm run build

# 3. Copy built UI into the server directory
Copy-Item -Path dist -Destination ..\takserver\server\frontend -Recurse -Force

# 4. Start the server
cd ..\takserver
docker compose up -d --build
```

You can also let the E2E script build the UI, start the stack, and verify the server:

```bash
python3 tools/e2e_test.py
```

This starts PostgreSQL, RabbitMQ, the OpenTAKServer Web UI/API, the CoT parser, and separate TCP/SSL CoT listener services.

### Container Overview

| Service | Image | Purpose |
|---------|-------|---------|
| `postgres` | postgres:16-alpine | Database (persistent via `postgres_data` volume) |
| `rabbitmq` | rabbitmq:3.13-management | Message broker (management UI on host port 15673) |
| `opentakserver` | built from `server/Dockerfile` | Flask Web UI + HTTP/Marti API |
| `cot_parser` | `takserver-opentakserver` | Persists and routes CoT events from RabbitMQ |
| `cot_tcp` | `takserver-opentakserver` | Plain TCP CoT listener on host port 8088 |
| `cot_ssl` | `takserver-opentakserver` | mTLS CoT listener on host port 8443 |

### Access Points

| Service | URL |
|---------|-----|
| Web UI | http://localhost:8089 |
| CoT TCP | tcp://localhost:8088 |
| CoT SSL | ssl://localhost:8443 |
| RabbitMQ Mgmt | http://localhost:15673 (`tak_user` / your `TAK_RABBITMQ_PASSWORD`) |

### First Login

Open `http://localhost:8089/` in browser:

| Field | Value |
|-------|-------|
| Username | `administrator` |
| Password | `password` |

**Important:** `SECURITY_PASSWORD_SALT` must be set in `config.yml` with a fixed value — otherwise OTS generates a random salt on every restart and the password becomes invalid.

### Configuration Flow

1. Edit `server/config/config.yml` (Flask-uppercase keys only)
2. Rebuild and restart: `docker compose up -d --build`
3. Config is auto-copied from image to volume on each start

### Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `postgres_data` | `/var/lib/postgresql/data` | Database files |
| `rabbitmq_data` | `/var/lib/rabbitmq` | Message queue data |
| `ots_data` | `/var/lib/opentakserver` | Server config, uploads, CA |
| `ots_certs` | `/etc/opentakserver/certs` | SSL certificates (auto-generated) |
| `ots_logs` | `/var/log/opentakserver` | Log files |

### Watching Logs

```powershell
docker compose logs -f opentakserver cot_parser cot_tcp cot_ssl
```

### Restarting

```powershell
docker compose restart                     # Quick restart
docker compose up -d --build               # Rebuild + restart
docker compose down                        # Stop all
```

---

## Testing

Run the E2E smoke test to verify the Docker stack:

```bash
python3 tools/e2e_test.py
```

It verifies the Web UI, health endpoint, Marti API, plaintext TCP CoT ingest, SSL CoT ingest, and database/API persistence.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Python not found" | Install Python 3.8+ and ensure it's in PATH |
| "Permission denied" | Run as Administrator (Windows) or use `sudo` (macOS) |
| "RabbitMQ won't start" | Check port 5672 is free: `netstat -an \| findstr 5672` |
| "Port already in use" | Change `OTS_LISTENER_PORT` in `config.yml` |
| "Empty reply from server" | Check `OTS_LISTENER_ADDRESS: "0.0.0.0"` in `config.yml` |
| "Connection refused" on 8089 | Verify container is running: `docker ps \| grep tak-server` |
| SSL handshake fails | Verify the client has a certificate issued by this server CA |
| "Certificate error" | Regenerate certs and update `config.yml` |
| "Service won't start" | Check logs at `/var/log/opentakserver/ots-err.log` |
| WinTAK connects but drops | Use port **8088** (dedicated CoT TCP), not 8089 (WebUI port) |

---

## Default Ports

| Port | Service | Protocol |
|------|---------|----------|
| 8089 | Web UI / HTTP/Marti API | TCP |
| 8088 | CoT TCP Streaming | TCP |
| 8443 | CoT SSL | TCP |
| 8554 | MediaMTX RTSP | TCP/UDP |
| 8889 | MediaMTX WebRTC | TCP |
| 9997 | MediaMTX API | TCP |
| 5432 | PostgreSQL (Docker internal) | TCP |
| 5672 | RabbitMQ (Docker internal) | TCP |
| 15673 | RabbitMQ Management (host) | TCP |

---

## Security Notes

1. Change default RabbitMQ credentials in `config.yml` before production use
2. Place the server behind a reverse proxy (nginx) for production
3. Use strong passwords for P12 client certificates
4. Keep `ca.key` secure – anyone with this key can forge certificates
5. Enable firewall and restrict port access to trusted networks
