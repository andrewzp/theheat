"""Encrypt results before upload; never emit plaintext source/history/drafts."""
import os
from pathlib import Path
import subprocess
import tarfile


def validate_recipient(base: Path, certificate: str) -> Path:
    cert = base / "trial-recipient.pem"
    cert.write_text(certificate)
    subprocess.run(["openssl", "x509", "-noout", "-checkend", "1800", "-in", str(cert)],
                   check=True, timeout=10, capture_output=True)
    # Verify encryption is supported BEFORE any paid call. Never require or send
    # the private key; its ownership is checked by the operator locally.
    subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER", str(cert)],
                   input=b"Trial recipient readiness", check=True, timeout=10, capture_output=True)
    return cert


def package(base: Path, certificate: str) -> None:
    cert = validate_recipient(base, certificate)
    plain = base / "sample-trial.tar.gz"
    with tarfile.open(plain, "w:gz") as archive:
        for name in ("sample-trial", "trial-plan-result.json"):
            if (base / name).exists():
                archive.add(base / name, arcname=name)
    subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-outform", "DER",
                    "-in", str(plain), "-out", str(base / "sample-trial.cms"), str(cert)],
                   check=True, timeout=30, capture_output=True)


if __name__ == "__main__":
    package(Path(os.environ["RUNNER_TEMP"]), os.environ["RECIPIENT_CERTIFICATE"])
    print("Encrypted results ready. No plaintext artifact is uploaded.")
