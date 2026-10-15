"""Encrypt results before upload; never emit plaintext source/history/drafts."""
import os
from pathlib import Path
import subprocess
import tarfile


def package(base: Path, certificate: str) -> None:
    cert = base / "trial-recipient.pem"
    cert.write_text(certificate)
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
