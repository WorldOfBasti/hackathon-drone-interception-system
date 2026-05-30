#!/usr/bin/env python3
"""
Certificate Generator for OpenTAKServer
Generates CA, server, and client certificates for TAK deployment.
"""

import argparse
import datetime
import os
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("cryptography package required: pip install cryptography")
    sys.exit(1)


def generate_private_key(key_size: int = 4096) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend(),
    )


def generate_cert(
    subject_name: str,
    issuer_name: str,
    subject_key,
    issuer_key,
    is_ca: bool = False,
    san_dns: list = None,
    san_ips: list = None,
    days_valid: int = 365,
) -> x509.Certificate:
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, subject_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TAK Drone Defense"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "TAK Server"),
        ]
    )

    issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, issuer_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TAK Drone Defense"),
        ]
    )

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_valid)
        )
    )

    if is_ca:
        builder = builder.add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    else:
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )

    if san_dns or san_ips:
        sans = []
        if san_dns:
            sans.extend(x509.DNSName(d) for d in san_dns)
        if san_ips:
            sans.extend(x509.IPAddress(ip) for ip in san_ips)
        builder = builder.add_extension(
            x509.SubjectAlternativeName(sans),
            critical=False,
        )

    return builder.sign(issuer_key, hashes.SHA256(), backend=default_backend())


def save_cert_and_key(
    output_dir: Path,
    prefix: str,
    cert: x509.Certificate,
    key,
    password: str = None,
):
    enc_alg = serialization.NoEncryption()
    if password:
        enc_alg = serialization.BestAvailableEncryption(password.encode("utf-8"))

    output_dir.mkdir(parents=True, exist_ok=True)

    cert_path = output_dir / f"{prefix}.crt"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    key_path = output_dir / f"{prefix}.key"
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=enc_alg,
        )
    )

    os.chmod(key_path, 0o600)
    print(f"  {cert_path}")
    print(f"  {key_path}")


def generate_p12(
    output_dir: Path,
    prefix: str,
    cert: x509.Certificate,
    key,
    password: str,
):
    from cryptography.hazmat.primitives.serialization import pkcs12

    p12 = pkcs12.serialize_key_and_certificates(
        name=prefix.encode("utf-8"),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8")),
    )

    p12_path = output_dir / f"{prefix}.p12"
    p12_path.write_bytes(p12)
    os.chmod(p12_path, 0o600)
    print(f"  {p12_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate TAK certificates for OpenTAKServer"
    )
    parser.add_argument(
        "-o", "--output",
        default="./certs",
        help="Output directory for certificates (default: ./certs)",
    )
    parser.add_argument(
        "--ca-name",
        default="DroneDefense-CA",
        help="CA common name (default: DroneDefense-CA)",
    )
    parser.add_argument(
        "--server-name",
        default="tak.dronedefense.local",
        help="Server common name / hostname (default: tak.dronedefense.local)",
    )
    parser.add_argument(
        "--client-name",
        default="operator",
        help="Client common name prefix (default: operator)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3650,
        help="Certificate validity in days (default: 3650 = ~10 years)",
    )
    parser.add_argument(
        "--key-size",
        type=int,
        default=4096,
        help="RSA key size (default: 4096)",
    )
    parser.add_argument(
        "--password",
        default="",
        help="Password for client P12 certificate (optional)",
    )
    parser.add_argument(
        "--server-san-dns",
        nargs="*",
        default=None,
        help="Additional DNS SANs for the server certificate",
    )
    parser.add_argument(
        "--server-san-ips",
        nargs="*",
        default=None,
        help="Additional IP SANs for the server certificate",
    )

    args = parser.parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  OpenTAKServer Certificate Generator")
    print("=" * 60)
    print()
    print(f"  Output:      {output_dir}")
    print(f"  CA Name:     {args.ca_name}")
    print(f"  Server:      {args.server_name}")
    print(f"  Valid:       {args.days} days")
    print(f"  Key size:    {args.key_size}")
    print()

    print("[1/4] Generating CA key...")
    ca_key = generate_private_key(args.key_size)

    print("[2/4] Generating CA certificate...")
    ca_cert = generate_cert(
        subject_name=args.ca_name,
        issuer_name=args.ca_name,
        subject_key=ca_key,
        issuer_key=ca_key,
        is_ca=True,
        days_valid=args.days,
    )
    save_cert_and_key(output_dir, "ca", ca_cert, ca_key)
    print()

    print("[3/4] Generating server key and certificate...")
    server_key = generate_private_key(args.key_size)

    server_dns = [args.server_name]
    if args.server_san_dns:
        server_dns.extend(args.server_san_dns)

    server_cert = generate_cert(
        subject_name=args.server_name,
        issuer_name=args.ca_name,
        subject_key=server_key,
        issuer_key=ca_key,
        san_dns=server_dns,
        san_ips=args.server_san_ips,
        days_valid=args.days,
    )
    save_cert_and_key(output_dir, "server", server_cert, server_key)
    print()

    print("[4/4] Generating client key and certificate...")
    client_key = generate_private_key(args.key_size)
    client_cert = generate_cert(
        subject_name=args.client_name,
        issuer_name=args.ca_name,
        subject_key=client_key,
        issuer_key=ca_key,
        san_dns=[args.client_name],
        days_valid=args.days,
    )
    save_cert_and_key(output_dir, "client", client_cert, client_key)

    pwd = args.password or "takserver"
    generate_p12(output_dir, "client", client_cert, client_key, pwd)
    print()

    print("=" * 60)
    print("  Certificate generation complete")
    print("=" * 60)
    print()
    print("  Files generated:")
    print(f"    ca.crt          - CA certificate (distribute to all clients)")
    print(f"    ca.key          - CA private key (keep secret!)")
    print(f"    server.crt      - Server certificate")
    print(f"    server.key      - Server private key")
    print(f"    client.crt      - Client certificate")
    print(f"    client.key      - Client private key")
    print(f"    client.p12      - Client bundle for WinTAK/iTAK (password: {pwd})")
    print()
    print("  Update config.yml:")
    print(f"    ssl_cert: {output_dir}/server.crt")
    print(f"    ssl_key:  {output_dir}/server.key")
    print(f"    ca_cert:  {output_dir}/ca.crt")
    print()


if __name__ == "__main__":
    main()
