#!/bin/bash
# OpenTAKServer macOS Installer
# Drone Defense TAK Server – macOS Setup
# Usage: chmod +x macos_install.sh && ./macos_install.sh

set -euo pipefail

SKIP_PYTHON=false
SKIP_RABBITMQ=false
SKIP_MEDIAMTX=false
SKIP_LAUNCHD=false
INSTALL_DIR="/usr/local/opentakserver"
DATA_DIR="/usr/local/var/opentakserver"
LOG_DIR="/usr/local/var/log/opentakserver"
CERT_DIR="${DATA_DIR}/certs"
CONFIG_SOURCE="../config/config.yml"
OTS_USER="_opentakserver"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "${YELLOW}[ ]${NC} $1"; }
ok()   { echo -e "${GREEN}[+]${NC} $1"; }
err()  { echo -e "${RED}[-]${NC} $1"; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-python)   SKIP_PYTHON=true; shift ;;
        --skip-rabbitmq) SKIP_RABBITMQ=true; shift ;;
        --skip-mediamtx) SKIP_MEDIAMTX=true; shift ;;
        --skip-launchd)  SKIP_LAUNCHD=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo -e "${CYAN}======================================================================"
echo -e "  OpenTAKServer – Drone Defense TAK Server Installation (macOS)"
echo -e "======================================================================${NC}"
echo ""

# ── macOS Version Check ──────────────────────────────────────────────────────
macos_version=$(sw_vers -productVersion 2>/dev/null || echo "0")
major=$(echo "$macos_version" | cut -d. -f1)
if [[ "$major" -lt 12 ]]; then
    err "macOS 12 (Monterey) or later required. Found: $macos_version"
fi
ok "macOS $macos_version detected"

# ── Homebrew ──────────────────────────────────────────────────────────────────
step "Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    step "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ "$(uname -m)" == "arm64" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
ok "Homebrew ready"

# ── Python ────────────────────────────────────────────────────────────────────
if [[ "$SKIP_PYTHON" != "true" ]]; then
    step "Checking Python 3.8+..."
    if command -v python3 &>/dev/null; then
        py_ver=$(python3 --version 2>&1 | awk '{print $2}')
        ok "Found Python $py_ver"
    else
        step "Installing Python via Homebrew..."
        brew install python@3.11
        py_ver=$(python3 --version 2>&1 | awk '{print $2}')
        ok "Python $py_ver installed"
    fi
else
    ok "Skipping Python (--skip-python)"
fi

# ── OpenTAKServer ─────────────────────────────────────────────────────────────
step "Installing OpenTAKServer..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="${SCRIPT_DIR}/../requirements.txt"

python3 -m pip install --upgrade pip --quiet

if [[ -f "$REQ_FILE" ]]; then
    python3 -m pip install -r "$REQ_FILE" --quiet || err "Failed to install dependencies"
else
    python3 -m pip install opentakserver --quiet || err "Failed to install OpenTAKServer"
fi
ok "OpenTAKServer installed"

# ── RabbitMQ ──────────────────────────────────────────────────────────────────
if [[ "$SKIP_RABBITMQ" != "true" ]]; then
    step "Installing RabbitMQ..."
    if brew list rabbitmq &>/dev/null; then
        ok "RabbitMQ already installed"
    else
        brew install rabbitmq
        ok "RabbitMQ installed"
    fi

    step "Starting RabbitMQ service..."
    brew services start rabbitmq
    ok "RabbitMQ service started"
else
    ok "Skipping RabbitMQ (--skip-rabbitmq)"
fi

# ── MediaMTX ──────────────────────────────────────────────────────────────────
if [[ "$SKIP_MEDIAMTX" != "true" ]]; then
    step "Installing MediaMTX..."

    MTX_VERSION="1.8.5"
    ARCH=$(uname -m)
    if [[ "$ARCH" == "arm64" ]]; then
        MTX_ARCH="arm64v8"
    else
        MTX_ARCH="amd64"
    fi

    MTX_URL="https://github.com/bluenviron/mediamtx/releases/download/v${MTX_VERSION}/mediamtx_v${MTX_VERSION}_darwin_${MTX_ARCH}.tar.gz"
    MTX_BIN="${INSTALL_DIR}/mediamtx"

    if [[ -x "$MTX_BIN/mediamtx" ]]; then
        ok "MediaMTX already installed"
    else
        mkdir -p "$MTX_BIN"
        curl -fsSL "$MTX_URL" -o /tmp/mediamtx.tar.gz
        tar -xzf /tmp/mediamtx.tar.gz -C "$MTX_BIN"
        rm -f /tmp/mediamtx.tar.gz
        chmod +x "$MTX_BIN/mediamtx"
        ok "MediaMTX installed to $MTX_BIN"
    fi
else
    ok "Skipping MediaMTX (--skip-mediamtx)"
fi

# ── Directory Structure ───────────────────────────────────────────────────────
step "Creating directory structure..."
mkdir -p "$DATA_DIR" "$LOG_DIR" "$CERT_DIR" "$INSTALL_DIR"
ok "Directories created"

# ── User & Permissions ────────────────────────────────────────────────────────
step "Setting up service user..."
if ! id -u "$OTS_USER" &>/dev/null; then
    sudo dscl . -create "/Users/$OTS_USER"
    sudo dscl . -create "/Users/$OTS_USER" UserShell /usr/bin/false
    sudo dscl . -create "/Users/$OTS_USER" UniqueID 600
    sudo dscl . -create "/Users/$OTS_USER" PrimaryGroupID 600
    sudo dscl . -create "/Users/$OTS_USER" NFSHomeDirectory "$DATA_DIR"
    ok "User $OTS_USER created"
fi

sudo chown -R "${OTS_USER}:staff" "$DATA_DIR" "$LOG_DIR" "$CERT_DIR"
ok "Permissions set"

# ── Configuration ─────────────────────────────────────────────────────────────
step "Copying configuration..."
CONFIG_SRC="${SCRIPT_DIR}/${CONFIG_SOURCE}"
if [[ ! -f "$CONFIG_SRC" ]]; then
    err "Config file not found: $CONFIG_SRC"
fi
cp "$CONFIG_SRC" "${DATA_DIR}/config.yml"
ok "Configuration copied to ${DATA_DIR}/config.yml"

# ── launchd Daemon ────────────────────────────────────────────────────────────
if [[ "$SKIP_LAUNCHD" != "true" ]]; then
    step "Setting up launchd daemon..."

    PLIST_PATH="/Library/LaunchDaemons/org.opentakserver.ots.plist"

    sudo tee "$PLIST_PATH" > /dev/null << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>org.opentakserver.ots</string>

    <key>ProgramArguments</key>
    <array>
        <string>$(which python3)</string>
        <string>-m</string>
        <string>opentakserver</string>
        <string>--config</string>
        <string>${DATA_DIR}/config.yml</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/ots-out.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/ots-err.log</string>

    <key>WorkingDirectory</key>
    <string>${DATA_DIR}</string>

    <key>UserName</key>
    <string>${OTS_USER}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${DATA_DIR}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
PLISTEOF

    sudo launchctl bootstrap system "$PLIST_PATH" 2>/dev/null || sudo launchctl load "$PLIST_PATH"
    ok "launchd daemon configured and loaded"
else
    ok "Skipping launchd (--skip-launchd)"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}======================================================================"
echo -e "  OpenTAKServer Installation Complete${NC}"
echo -e "${CYAN}======================================================================${NC}"
echo ""
echo -e "  Web UI:     ${GREEN}http://localhost:8089${NC}"
echo -e "  SSL Port:   ${GREEN}8443${NC}"
echo -e "  RTSP:       ${GREEN}8554${NC} (MediaMTX)"
echo -e "  Config:     ${GREEN}${DATA_DIR}/config.yml${NC}"
echo ""
echo -e "  Start:      ${YELLOW}sudo launchctl kickstart system/org.opentakserver.ots${NC}"
echo -e "  Stop:       ${YELLOW}sudo launchctl bootout system/org.opentakserver.ots${NC}"
echo -e "  Status:     ${YELLOW}sudo launchctl print system/org.opentakserver.ots${NC}"
echo ""
