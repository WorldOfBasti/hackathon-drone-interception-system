# iTAK / ATAK Connection Guide

## Connection QR Code

Generate a connection QR code for easy iTAK/ATAK setup.

### Method 1: QR Code Generator

Use any QR code generator with the following URL format:

```
https://tak.gov/enroll?host=tak.dronedefense.local&port=8089&tls=true&name=Drone+Defense
```

Or for local IP:

```
https://tak.gov/enroll?host=192.168.1.100&port=8089&tls=true&name=Drone+Defense+TAK
```

### Method 2: Generate QR Code via Python

```bash
pip install qrcode[pil]
python -c "
import qrcode
data = 'https://tak.gov/enroll?host=tak.dronedefense.local&port=8089&tls=true&name=Drone+Defense'
img = qrcode.make(data)
img.save('connection_qr.png')
print('QR code saved to connection_qr.png')
"
```

### Method 3: iTAK Manual Setup

1. Open iTAK on your iOS device
2. Go to **Settings > Servers**
3. Tap **+** to add a new server
4. Enter the following:

   | Setting | Value |
   |---------|-------|
   | **Server Name** | Drone Defense TAK |
   | **Server Address** | `tak.dronedefense.local` |
   | **Server Port** | `8089` (CoT) or `8443` (SSL) |
   | **Use SSL/TLS** | Enabled (for port 8443) |
   | **Authentication** | Certificate |

5. Import your client certificate (.p12)
6. Enable **GPS Reporting** to share your position
7. Tap **Connect**

## Certificate Import

### On iTAK

1. Email the `client.p12` file to your iOS device
2. Tap the attachment in Mail
3. iOS will prompt to install the profile
4. Go to **Settings > General > VPN & Device Management**
5. Install the certificate profile
6. In iTAK, the certificate will appear in the server settings

### On ATAK (Android)

1. Transfer the `client.p12` file to the device
2. In ATAK: **Settings > Network Preferences > Certificate Management**
3. Import the P12 file
4. Select it in the server connection settings

## Testing Connection

1. Connect your iTAK/ATAK to the server
2. You should see your position on the map
3. Open the Web Dashboard at `http://<server>:8089`
4. Verify your client appears in the Active Clients list
5. Send a test message: in iTAK, long-press on the map and select "Send to Team"

---

## Connection URL Format

The TAK server enrollment URL format:

```
https://<server>/Marti/sync/mission?<parameters>
```

Common parameters:
- `host` – Server hostname
- `port` – Server port
- `tls=true` – Use SSL
- `name` – Connection display name
- `enroll=true` – Auto-enroll mode
