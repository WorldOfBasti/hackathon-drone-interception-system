#!/usr/bin/env python3
"""
TCP CoT test client for OpenTAKServer.

Connects to a TAK server and sends test CoT messages.
"""

import argparse
import asyncio
import datetime
import random
import signal
import socket
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional


def create_cot_uid(callsign: str, uid_type: str) -> str:
    return f"drone-defense-{callsign}-{uid_type}"


def build_cot_event(
    uid: str,
    cot_type: str,
    lat: float,
    lon: float,
    hae: float = 0.0,
    stale_seconds: int = 120,
    callsign: str = "test-drone",
) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    stale = now + datetime.timedelta(seconds=stale_seconds)

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", uid)
    event.set("type", cot_type)
    event.set("time", now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    event.set("start", now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    event.set("stale", stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    event.set("how", "m-g")

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lon))
    point.set("hae", str(hae))
    point.set("ce", "2.0")
    point.set("le", "2.0")

    detail = ET.SubElement(event, "detail")
    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", callsign)

    ET.SubElement(detail, "precisionlocation")
    remarks = ET.SubElement(detail, "remarks")
    remarks.text = f"TCP CoT test client – {cot_type}"

    track = ET.SubElement(detail, "track")
    track.set("course", str(random.uniform(0, 360)))
    track.set("speed", str(random.uniform(0, 30)))

    return ET.tostring(event, encoding="unicode")


def co_listener(data):
    print(f"\n  <-- CoT received: {data[:200]}...")


class TAKTestClient:
    def __init__(
        self,
        host: str,
        port: int,
        use_ssl: bool = False,
        cert: Optional[str] = None,
        key: Optional[str] = None,
        ca: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.cert = cert
        self.key = key
        self.ca = ca
        self.running = False
        self.cot_count = 0

    def _connect(self):
        raw_sock = socket.create_connection((self.host, self.port), timeout=10)
        if not self.use_ssl:
            return raw_sock

        if not self.cert or not self.key:
            raw_sock.close()
            raise RuntimeError("--cert and --key are required for SSL CoT connections")

        context = ssl.create_default_context(cafile=self.ca)
        if not self.ca:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        context.load_cert_chain(certfile=self.cert, keyfile=self.key)
        return context.wrap_socket(raw_sock, server_hostname=self.host)

    async def connect_and_send(self, duration: int, interval: float, cot_type: str):
        self.running = True
        start_time = time.time()
        lat = 48.137
        lon = 11.575
        uid = create_cot_uid(f"test-{random.randint(1000, 9999)}", cot_type)

        with self._connect() as sock:
            print(f"Connected to {self.host}:{self.port} (SSL: {self.use_ssl})")
            print(f"Sending CoT type: {cot_type} every {interval}s for {duration}s")
            print(f"UID/callsign: {uid}")
            print(f"Starting position: {lat}, {lon} (Munich center)")
            print("-" * 60)

            while self.running and (time.time() - start_time) < duration:
                current_lat = lat + random.uniform(-0.01, 0.01)
                current_lon = lon + random.uniform(-0.01, 0.01)
                hae = random.uniform(50, 150)

                cot_xml = build_cot_event(
                    uid=uid,
                    cot_type=cot_type,
                    lat=current_lat,
                    lon=current_lon,
                    hae=hae,
                    callsign=uid,
                )
                sock.sendall(cot_xml.encode("utf-8"))

                self.cot_count += 1
                elapsed = time.time() - start_time

                sys.stdout.write(
                    f"\r  [#{self.cot_count:04d}] Elapsed: {elapsed:6.1f}s  "
                    f"Position: {current_lat:.5f}, {current_lon:.5f}  HAE: {hae:.0f}m"
                )
                sys.stdout.flush()

                await asyncio.sleep(interval)

        print()
        print("-" * 60)
        print(f"Test complete. Sent {self.cot_count} CoT events.")
        print(f"Average rate: {self.cot_count / duration:.2f} events/sec")

    def _simulate(self, duration, interval, cot_type, lat, lon):
        start_time = time.time()

        while self.running and (time.time() - start_time) < duration:
            current_lat = lat + random.uniform(-0.01, 0.01)
            current_lon = lon + random.uniform(-0.01, 0.01)
            hae = random.uniform(50, 150)

            cot_xml = build_cot_event(
                uid=create_cot_uid(f"sim-{random.randint(1000, 9999)}", cot_type),
                cot_type=cot_type,
                lat=current_lat,
                lon=current_lon,
                hae=hae,
            )

            self.cot_count += 1
            elapsed = time.time() - start_time
            sys.stdout.write(
                f"\r  [SIM #{self.cot_count:04d}] Elapsed: {elapsed:6.1f}s  "
                f"Position: {current_lat:.5f}, {current_lon:.5f}"
            )
            sys.stdout.flush()
            time.sleep(interval)

    def stop(self):
        self.running = False


def main():
    parser = argparse.ArgumentParser(
        description="TCP CoT test client for OpenTAKServer"
    )
    parser.add_argument("--host", default="localhost", help="TAK server host")
    parser.add_argument("--port", type=int, default=8088, help="TAK server CoT port")
    parser.add_argument("--ssl", action="store_true", help="Use SSL/TLS")
    parser.add_argument("--cert", help="Client certificate PEM for SSL CoT")
    parser.add_argument("--key", help="Client private key PEM for SSL CoT")
    parser.add_argument("--ca", help="Server CA PEM for SSL CoT")
    parser.add_argument(
        "-t", "--type",
        default="a-f-A-M",
        help="CoT event type (default: a-f-A-M = UAV/Drone)",
    )
    parser.add_argument(
        "-d", "--duration",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60)",
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=2.0,
        help="Interval between CoT events in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--cot-list",
        action="store_true",
        help="Show common CoT types and exit",
    )

    args = parser.parse_args()

    if args.cot_list:
        print("Common CoT Event Types:")
        print("  a-f-A-M     UAV/Drone")
        print("  a-f-A-M-H   Hostile UAV/Drone")
        print("  a-f-A-M-F   Friendly UAV/Drone")
        print("  a-n-A-M     Unknown UAV/Drone")
        print("  a-f-G       GCS (Ground Control Station)")
        print("  b-m-p-s-r   Radar Track")
        print("  b-a-o-tbl   Sensor Observation")
        print("  a-u-A       Air Defense Unit")
        return

    if args.ssl and args.port == 8088:
        args.port = 8443

    print("=" * 60)
    print("  TCP CoT Test Client – Drone Defense")
    print("=" * 60)
    print(f"  Server:   {args.host}:{args.port}")
    print(f"  SSL:      {args.ssl}")
    print(f"  CoT Type: {args.type}")
    print(f"  Duration: {args.duration}s")
    print("-" * 60)

    client = TAKTestClient(args.host, args.port, args.ssl, args.cert, args.key, args.ca)

    async def run():
        await client.connect_and_send(
            duration=args.duration,
            interval=args.interval,
            cot_type=args.type,
        )

    def shutdown(*_):
        client.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        client.stop()
    except RuntimeError as e:
        if "asyncio.run()" in str(e):
            loop = asyncio.get_event_loop_policy().get_event_loop()
            try:
                loop.run_until_complete(run())
            except KeyboardInterrupt:
                client.stop()
        else:
            raise


if __name__ == "__main__":
    main()
