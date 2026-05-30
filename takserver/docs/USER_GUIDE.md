# OpenTAKServer – Drone Defense User Guide

## Server Access

Once installed, access the server through these interfaces:

| Interface | URL | Purpose |
|-----------|-----|---------|
| Web Dashboard | `http://<server>:8089` | Flask Web UI + API (register first user as admin) |
| CoT TCP Streaming | `tcp://<server>:8088` | Plain TCP CoT event stream |
| CoT SSL | `ssl://<server>:8443` | Secure CoT connections |
| MediaMTX | `rtsp://<server>:8554` | Video streams from drones (optional, via `--profile video`) |

## First Login

**Browser:** `http://localhost:8089/`

OTS creates a default administrator on first start:

| Field | Value |
|-------|-------|
| Username | `administrator` |
| Password | `password` |

If the default admin is already used, you can register a new user at `http://localhost:8089/`
— the first registered user automatically gets administrator privileges (when `OTS_ENABLE_EMAIL` is `false`).

**Change the default password immediately** after first login under **User Profile > Change Password**.

### What you can do in the WebUI

| Feature | Description |
|---------|-------------|
| Dashboard | Live map with real-time CoT event positions |
| Map | Full TAK map with drone/UAV tracks |
| Missions | Create and manage operational missions |
| Users | Manage user accounts and roles |
| Groups | Organize users into groups (LDAP-compatible) |
| Devices (EUDs) | Register and manage TAK clients |
| Device Profiles | Connection profiles for ATAK/WinTAK/iTAK |
| Data Packages | Serve files, KML, mission packages to clients |
| Alerts | Configure geo-fence and event alerts |
| Scheduled Jobs | Manage ADS-B, AIS, purge tasks |
| Plugins | Install and manage OTS plugins |
| Federation (Link TAK.gov) | Connect to external TAK servers |

---

## Connecting Clients

### WinTAK (Windows)

1. Launch WinTAK
2. Go to **Settings > Network Preferences > Manage Server Connections**
3. Select **Add Server** and enter:
   - **Host Address:** `localhost` (or server IP)
   - **Port:** `8088` (TCP CoT) or `8443` (SSL CoT)
   - **Protocol:** TCP
   - **Description:** `Drone Defense Server`
4. No certificate needed for local TCP — OTS accepts plain CoT
5. Connect and verify the green connection indicator

### iTAK (iOS)

1. Open iTAK and go to **Settings**
2. Tap **Servers > Add Server**
3. Enter: Host `localhost`, Port `8088`, Protocol `TCP`
4. Enable **GPS Reporting** to share your position on the TAK map

### ATAK (Android)

1. Install the ATAK APK from tak.gov
2. Go to **Settings > Network Preferences > Manage Servers**
3. Add a new TAK Server connection
4. Import the Data Package or enter manual settings
5. Connect

---

## Drone-Specific CoT Event Types

CoT (Cursor on Target) is the communication protocol used by TAK. These are drone-specific event types:

| CoT Type | Description | Icon |
|----------|-------------|------|
| `a-f-A-M` | Drone / UAV | Default UAV icon |
| `a-f-A-M-H` | Hostile UAV | Red UAV icon |
| `a-f-A-M-F` | Friendly UAV | Blue UAV icon |
| `a-f-A-M-N` | Neutral UAV | Green UAV icon |
| `a-f-A-M-U` | Unknown UAV | Yellow UAV icon |
| `a-f-G` | Ground Control Station (GCS) | Antenna icon |
| `b-m-p-s-r` | Radar Track | Radar icon |
| `b-a-o-tbl` | Sensor Observation | Target icon |
| `a-u-A` | Air Defense Unit | Shield icon |

---

## Dashboard Overview

The OpenTAKServer Web Dashboard provides:

- **Live Map:** Real-time positions of all connected assets
- **Event Log:** Chronological list of all CoT events
- **Active Clients:** List of currently connected clients
- **Server Stats:** Uptime, message rate, bandwidth usage
- **Mission Manager:** Create and manage missions

---

## Managing Missions

Missions allow coordinated operations:

1. Go to the **Missions** tab in the Web Dashboard
2. Click **Create Mission**
3. Set:
   - Mission name
   - Operational area (bounding box)
   - Assigned assets / operators
   - Expiration time
4. All assigned clients will receive the mission

---

## Video Streaming (MediaMTX)

MediaMTX enables real-time video from drones:

### Publishing a Stream (from drone to server)

```bash
# Using FFmpeg from a drone's video feed
ffmpeg -i /dev/video0 -c:v h264 -f rtsp rtsp://<server>:8554/drone-cam-1
```

### Viewing a Stream

- **RTSP:** `rtsp://<server>:8554/drone-cam-1`
- **WebRTC:** `http://<server>:8889/drone-cam-1`
- **HLS:** `http://<server>:8888/drone-cam-1`

The TAK client will automatically display the video stream if the CoT event includes a video URL in its remarks.

---

## Geo-Fencing

Configure the geo-fence in the OTS Web Dashboard after logging in.  
Geo-fencing is managed via the OTS API at `POST /api/alerts` with alert rules (not via config.yml).

Assets entering or leaving the geo-fence trigger alerts. The Web UI shows geo-fence boundaries on the map.

---

## Federation

Connect multiple TAK servers via the OTS Web Dashboard under **Settings > Federation**.  
Federation config keys are set in `config.yml` as Flask-uppercase keys:

```yaml
OTS_ENABLE_FEDERATION: true
OTS_FEDERATE_NAME: "drone-defense"
```

Federation enables sharing situational awareness across operational boundaries.

---

## Testing the Stack

The E2E smoke test starts the Docker stack if needed, verifies the Web UI and Marti API, sends real CoT over TCP and SSL, then confirms those events are queryable through the API:

```bash
python3 tools/e2e_test.py
```

For a lightweight local TCP simulation after the stack is already running, use the test client against the CoT TCP listener:

```bash
# Simulate a drone flying near Munich
python tools/test_client.py --host localhost --port 8088 -t a-f-A-M -d 30

# Simulate radar tracks
python tools/test_client.py --host localhost --port 8088 -t b-m-p-s-r -d 60 -i 0.5

# Show all available CoT types
python tools/test_client.py --cot-list
```

---

## Useful Commands

```bash
# Windows – PowerShell
Get-Service OpenTAKServer              # Service status
Restart-Service OpenTAKServer          # Restart server
Get-Content %ProgramData%\OpenTAKServer\*.log -Tail 50  # View logs

# macOS
sudo launchctl kickstart system/org.opentakserver.ots   # Start
sudo launchctl bootout system/org.opentakserver.ots     # Stop
tail -f /usr/local/var/log/opentakserver/ots-out.log    # Logs
```

---

## Data Package Format

Data Packages (`.zip.pref` files) contain pre-configured server settings:

```
server_config.pref (ZIP archive)
  ├── manifest.xml       # Package metadata
  ├── connection.xml     # Server connection details
  ├── client.crt         # Client certificate (PEM)
  ├── client.key         # Client private key (PEM, encrypted)
  └── server.crt         # CA certificate (PEM)
```

The `packager.py` tool in `tools/cert_gen/` can create these packages automatically.

---

## Performance Tuning

For larger deployments, adjust `server/config/config.yml` with Flask-uppercase keys:

```yaml
# Use PostgreSQL (already configured in Docker setup)
SQLALCHEMY_DATABASE_URI: "postgresql+psycopg://ots:${TAK_POSTGRES_PASSWORD}@postgres:5432/ots"

# Increase RabbitMQ prefetch for high-throughput
OTS_RABBITMQ_PREFETCH: 10

# Adjust log level to reduce I/O
OTS_LOG_LEVEL: "WARNING"
```

---

## Troubleshooting Common Issues

### Client won't connect

1. Verify the server is running (`Get-Service OpenTAKServer` / `launchctl print`)
2. Check firewall rules (ports 8088, 8089, 8443 must be open)
3. Verify certificate is valid and not expired
4. Check that client time is synchronized (NTP)

### Video stream not showing

1. Verify MediaMTX is running
2. Check the RTSP URL in the CoT remarks field
3. Test the stream directly: `ffplay rtsp://localhost:8554/drone-cam-1`
4. Verify codec compatibility (H.264 recommended)

### High CPU usage

1. Reduce logging level from `DEBUG` to `INFO` in `config.yml`
2. Enable geo-fencing to filter irrelevant events
3. Reduce `max_pending_messages` value
4. Consider using PostgreSQL instead of SQLite for high-throughput scenarios
