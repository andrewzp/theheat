"""Explicit once-per-run dependency capture from the installed local runtime."""

from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from src.media import native_profile


def capture_with_diagnostics(executable):
    """Report only the last trusted loader inspection; never change its behavior."""
    original = native_profile.subprocess
    last = {}

    def inspect(*args, **kwargs):
        result = original.run(*args, **kwargs)
        # Native capture passes one argv list and bounds both outputs itself.
        # Keep only one record, with those same byte limits, on fixture failure.
        last.clear()
        last.update(argv=args[0], returncode=result.returncode,
                    stdout=result.stdout[:256 * 1024].decode("utf-8", errors="replace"),
                    stderr=result.stderr[:256 * 1024].decode("utf-8", errors="replace"),
                    stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr))
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(native_profile, "subprocess", SimpleNamespace(run=inspect))
        try:
            return native_profile.capture(executable)
        except Exception:
            if last:
                print("NATIVE_CAPTURE_LAST_INSPECTION=" + native_profile.encoded(last).decode("utf-8"))
            raise


@pytest.fixture(scope="session")
def native_dependencies(tmp_path_factory):
    executable = shutil.which("pdftoppm")
    assert executable, "The requested native profile requires pdftoppm"
    executable = str(Path(executable).resolve())
    folder = tmp_path_factory.mktemp("native-dependency-profile")
    filename = folder / "manifest.json"
    manifest = capture_with_diagnostics(executable)
    filename.write_bytes(native_profile.encoded(manifest))
    filename.chmod(0o600)
    return dict(rasterizer=executable, dependency_manifest=str(filename))
