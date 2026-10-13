"""Short-lived synthetic CA and server certificates for an isolated Docker test."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def create_tls_fixture(root: Path, hostname: str) -> None:
    now = datetime.now(UTC)

    def certificate(
        name: str, *, issuer: x509.Certificate | None = None,
        issuer_key: rsa.RSAPrivateKey | None = None, server: bool = False,
    ) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        builder = (x509.CertificateBuilder().subject_name(subject)
                   .issuer_name(issuer.subject if issuer else subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                   .not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=not server, path_length=None), critical=True))
        if server:
            builder = (builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
                       .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False))
        return key, builder.sign(issuer_key or key, hashes.SHA256())

    ca_key, ca = certificate("Isolated PostgreSQL qualification CA")
    _, wrong_ca = certificate("Untrusted PostgreSQL qualification CA")
    server_key, server = certificate(hostname, issuer=ca, issuer_key=ca_key, server=True)
    for name in ("server", "trusted", "untrusted"):
        (root / name).mkdir(mode=0o755)
    for directory, cert in (("trusted", ca), ("untrusted", wrong_ca)):
        path = root / directory / "ca.crt"
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        path.chmod(0o644)
    (root / "server/server.crt").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    private_key = root / "server/server.key"
    private_key.write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_key.chmod(0o600)
    (root / "server/pg_hba.conf").write_text(
        "local all all trust\n"
        "hostssl all all 0.0.0.0/0 scram-sha-256\n"
        "hostssl all all ::/0 scram-sha-256\n"
        "hostnossl all all 0.0.0.0/0 reject\n"
        "hostnossl all all ::/0 reject\n", encoding="utf-8")
