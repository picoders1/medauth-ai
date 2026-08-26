#!/usr/bin/env bash
# Generate an ISOLATED test CA and server certificates for the local
# production-shaped environment.
#
#     bash scripts/make_local_tls.sh
#
# ## Why a CA and not a self-signed certificate
#
# A self-signed certificate can only be trusted by turning verification off, or by
# pinning that exact certificate. Both are habits that survive into production. A CA
# means MEDAUTH does the **real** thing - full chain construction, signature
# verification, hostname matching, expiry - against a trust anchor that happens to be
# local. The code path is identical to production; only the anchor differs.
#
# Nothing here is production TLS, and this CA must never leave this machine. It exists
# so that "TLS verification is enabled and working" is a tested statement rather than
# an aspiration.
#
# Output goes to `deploy/local-tls/`, which is gitignored: the CA private key is a
# key, and keys are not committed even when they are throwaway.
set -euo pipefail

OUT="${MEDAUTH_TLS_DIR:-deploy/local-tls}"
IDP_HOST="${MEDAUTH_IDP_HOSTNAME:-idp.medauth.localhost}"
API_HOST="${MEDAUTH_API_HOSTNAME:-api.medauth.localhost}"
DAYS="${MEDAUTH_TLS_DAYS:-90}"

mkdir -p "$OUT"
python3 - "$OUT" "$IDP_HOST" "$API_HOST" "$DAYS" <<'PY'
import datetime as dt
import ipaddress
import pathlib
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

out = pathlib.Path(sys.argv[1])
idp_host, api_host, days = sys.argv[2], sys.argv[3], int(sys.argv[4])
# Fixed clock arithmetic only - no wall-clock surprises in the not-before.
now = dt.datetime.now(dt.UTC)


def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def write(path: pathlib.Path, data: bytes, *, secret: bool) -> None:
    path.write_bytes(data)
    path.chmod(0o600 if secret else 0o644)


# -- the CA ------------------------------------------------------------------
ca_key = key()
ca_name = x509.Name([
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MEDAUTH local non-production"),
    x509.NameAttribute(NameOID.COMMON_NAME, "MEDAUTH local test CA - NOT FOR PRODUCTION"),
])
ca = (
    x509.CertificateBuilder()
    .subject_name(ca_name).issuer_name(ca_name)
    .public_key(ca_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - dt.timedelta(minutes=5))
    .not_valid_after(now + dt.timedelta(days=days))
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    .add_extension(
        x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                      content_commitment=False, key_encipherment=False,
                      data_encipherment=False, key_agreement=False,
                      encipher_only=False, decipher_only=False),
        critical=True,
    )
    .sign(ca_key, hashes.SHA256())
)
write(out / "ca.crt", ca.public_bytes(serialization.Encoding.PEM), secret=False)
write(out / "ca.key", ca_key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()), secret=True)


def leaf(hostname: str, stem: str) -> None:
    k = key()
    names = [x509.DNSName(hostname), x509.DNSName("localhost"),
             x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(ca_name)
        .public_key(k.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    write(out / f"{stem}.crt", cert.public_bytes(serialization.Encoding.PEM), secret=False)
    write(out / f"{stem}.key", k.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()), secret=True)
    print(f"  {stem}: CN={hostname}, SAN={hostname},localhost,127.0.0.1")


leaf(idp_host, "idp")
leaf(api_host, "api")
print(f"  CA valid {days} days. Trust anchor: {out}/ca.crt")
PY
