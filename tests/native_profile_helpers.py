"""Explicit once-per-run dependency capture from the installed local runtime."""

from pathlib import Path
import shutil

import pytest

from src.media import native_profile


@pytest.fixture(scope="session")
def native_dependencies(tmp_path_factory):
    executable = shutil.which("pdftoppm")
    assert executable, "The requested native profile requires pdftoppm"
    executable = str(Path(executable).resolve())
    folder = tmp_path_factory.mktemp("native-dependency-profile")
    filename = folder / "manifest.json"
    manifest = native_profile.capture(executable)
    filename.write_bytes(native_profile.encoded(manifest))
    filename.chmod(0o600)
    return dict(rasterizer=executable, dependency_manifest=str(filename))
