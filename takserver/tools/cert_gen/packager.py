#!/usr/bin/env python3
"""
TAK Data Package Generator
Creates .zip.pref packages for WinTAK/iTAK/ATAK client import.
"""

import argparse
import shutil
import os
import sys
from pathlib import Path


MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<MissionPackageManifest version="2">
    <Configuration>
        <Parameter name="uid" value="{uid}"/>
        <Parameter name="name" value="{name}"/>
        <Parameter name="version" value="{version}"/>
        <Parameter name="onReceiveDelete" value="true"/>
    </Configuration>
    <Contents>
        <Content ignore="false" zipEntry="{connection_file}"/>
        <Content ignore="false" zipEntry="{client_cert}"/>
        <Content ignore="false" zipEntry="{ca_cert}"/>
    </Contents>
</MissionPackageManifest>
"""

CONNECTION_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<ConnectionEntry version="2.0">
    <ConnectionParam name="description" value="{description}"/>
    <ConnectionParam name="host" value="{host}"/>
    <ConnectionParam name="port" value="{port}"/>
    <ConnectionParam name="protocol" value="tcp"/>
    <ConnectionParam name="useAuth" value="{use_auth}"/>
    <ConnectionParam name="authType" value="certificate"/>
    <ConnectionParam name="clientCert" value="{client_cert}"/>
    <ConnectionParam name="caCert" value="{ca_cert}"/>
    <ConnectionParam name="enableTls" value="{enable_tls}"/>
    <ConnectionParam name="rosterPort" value="{port}"/>
    <ConnectionParam name="chatPort" value="{port}"/>
</ConnectionEntry>
"""


def create_data_package(
    output_path: Path,
    host: str,
    port: int,
    use_tls: bool,
    client_cert_path: Path,
    ca_cert_path: Path,
    name: str = "Drone Defense TAK Server",
):
    import datetime

    uid = f"drone-defense-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    version = datetime.datetime.now().strftime("%Y.%m.%d")

    tmp_dir = output_path.parent / ".tmp_package"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    connection_file = "connection.xml"
    client_cert_file = "client.crt"
    ca_cert_file = "ca.crt"

    manifest_xml = MANIFEST_TEMPLATE.format(
        uid=uid,
        name=name,
        version=version,
        connection_file=connection_file,
        client_cert=client_cert_file,
        ca_cert=ca_cert_file,
    )

    connection_xml = CONNECTION_TEMPLATE.format(
        description=name,
        host=host,
        port=port,
        use_auth="true",
        client_cert=client_cert_file,
        ca_cert=ca_cert_file,
        enable_tls="true" if use_tls else "false",
    )

    (tmp_dir / "manifest.xml").write_text(manifest_xml)
    (tmp_dir / connection_file).write_text(connection_xml)

    if client_cert_path.exists():
        shutil.copy(client_cert_path, tmp_dir / client_cert_file)
    else:
        print(f"Warning: Client cert not found at {client_cert_path}")

    if ca_cert_path.exists():
        shutil.copy(ca_cert_path, tmp_dir / ca_cert_file)
    else:
        print(f"Warning: CA cert not found at {ca_cert_path}")

    zip_base = output_path.with_suffix("")
    shutil.make_archive(str(zip_base), "zip", tmp_dir)

    zip_path = Path(str(zip_base) + ".zip")
    if output_path.exists():
        output_path.unlink()
    zip_path.rename(output_path)

    shutil.rmtree(tmp_dir)
    print(f"Data Package created: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate TAK Data Package for client import"
    )
    parser.add_argument(
        "--host",
        default="tak.dronedefense.local",
        help="TAK server hostname or IP",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8089,
        help="TAK server port (default: 8089)",
    )
    parser.add_argument(
        "--tls",
        action="store_true",
        help="Enable TLS/SSL (port 8443)",
    )
    parser.add_argument(
        "--client-cert",
        default="certs/client.crt",
        help="Path to client certificate PEM (default: certs/client.crt)",
    )
    parser.add_argument(
        "--ca-cert",
        default="certs/ca.crt",
        help="Path to CA certificate PEM (default: certs/ca.crt)",
    )
    parser.add_argument(
        "-o", "--output",
        default="../../clients/wintak/DEFENSE-Server-Config.pref",
        help="Output .pref file path",
    )
    parser.add_argument(
        "--name",
        default="Drone Defense TAK Server",
        help="Connection name displayed in TAK clients",
    )

    args = parser.parse_args()

    if args.tls:
        args.port = args.port if args.port != 8089 else 8443

    script_dir = Path(__file__).resolve().parent
    output_path = (script_dir / args.output).resolve()
    client_cert_path = (script_dir / args.client_cert).resolve()
    ca_cert_path = (script_dir / args.ca_cert).resolve()

    print("=" * 60)
    print("  TAK Data Package Generator")
    print("=" * 60)
    print()
    print(f"  Server:   {args.host}:{args.port}")
    print(f"  TLS:      {args.tls}")
    print(f"  Name:     {args.name}")
    print(f"  Output:   {output_path}")
    print()

    create_data_package(
        output_path=output_path,
        host=args.host,
        port=args.port,
        use_tls=args.tls,
        client_cert_path=client_cert_path,
        ca_cert_path=ca_cert_path,
        name=args.name,
    )

    print()
    print("Import this file in your TAK client:")
    print("  WinTAK: File > Import Package > select .pref file")
    print("  ATAK:   Settings > Network > Import Package")
    print("  iTAK:   Settings > Servers > Import Configuration")


if __name__ == "__main__":
    main()
