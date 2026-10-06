"""Explicit, offline packaging for private review; no rendering or approval.

Paths must be absolute, local and free of symlinks (including their ancestors).
Descriptor-relative I/O prevents symlink swaps from redirecting file access.
Cooperating writers serialize under a private-root lock; a hostile process with
the same user privileges is outside this local filesystem trust boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Iterator
import uuid

from src.media.evidence_graphic import adapter_filename
from src.media.review_packet import (
    MAX_JSON_BYTES,
    MAX_PNG_BYTES,
    MediaReviewError,
    build_media_review_packet,
)

_ASSETS = {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}
_LIMITS = {name: MAX_PNG_BYTES for name in _ASSETS}
_LIMITS.update({"input.json": MAX_JSON_BYTES, "alt.txt": MAX_JSON_BYTES})
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_BINARY_LIMIT = 64 * 1024 * 1024


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MediaReviewError(message)


def _path(value: Path) -> Path:
    raw = os.fspath(value)
    _require(
        isinstance(raw, str)
        and raw.startswith("/")
        and not raw.startswith("//")
        and ".." not in raw.split("/")
        and all(ord(c) >= 32 for c in raw),
        "Select an absolute local path without traversal or control characters",
    )
    return Path(raw)


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    """Walk from / without ever following a directory symlink."""
    fd = os.open("/", _DIRECTORY)
    try:
        for component in _path(path).parts[1:]:
            child = os.open(component, _DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read_at(directory: int, name: str, limit: int, *, private: bool = False) -> bytes:
    fd = os.open(name, _READ, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode), "Input must be a regular local file")
        _require(before.st_size <= limit, "Input exceeds its byte bound")
        if private:
            _require(
                stat.S_IMODE(before.st_mode) == 0o600
                and before.st_uid == os.getuid()
                and before.st_nlink == 1,
                "Existing package file is not private or has another hard link",
            )
        data = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _require(len(data) <= limit, "Input exceeds its byte bound")
    _require(
        (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        and len(data) == before.st_size,
        "Input changed while being read",
    )
    return data


def _read(path: Path, limit: int) -> bytes:
    with _directory(path.parent) as directory:
        return _read_at(directory, path.name, limit)


def _pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON keys are not allowed")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise MediaReviewError("Nonfinite JSON numbers are not allowed")


def _json(data: bytes) -> dict:
    result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    _require(isinstance(result, dict), "Review JSON must contain an object")
    # Reject nonfinite float overflow, lone Unicode surrogates and deep objects.
    _encode(result)
    return result


def _encode(value: dict) -> bytes:
    encoded = (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    _require(len(encoded) <= MAX_JSON_BYTES, "Review JSON exceeds its byte bound")
    return encoded


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_renderer(manifest: dict, rasterizer: Path) -> None:
    """Verify retained provenance against local code/font/tool, without executing it.

    ReportLab version is retained provenance, not attestation of an installed
    environment. This adapter neither imports the optional backend nor certifies
    the image's content or external libraries linked by the rasterizer.
    """
    media = Path(__file__).resolve().parent
    expected = {
        "implementation_sha256": media / "evidence_graphic_render.py",
        "contract_sha256": media / "evidence_graphic.py",
        "adapter_sha256": media / adapter_filename(manifest["binding"]["template"]),
        "font_sha256": media / "fonts" / "DejaVuSansMono.ttf",
        "rasterizer_sha256": rasterizer,
    }
    actual = manifest["binding"]["renderer"]
    for key, path in expected.items():
        _require(
            actual[key] == _digest(_read(path, _BINARY_LIMIT)),
            "Preview renderer differs from the selected local implementation or tool",
        )


def _fence(text: str) -> str:
    delimiter = "`" * max(3, 1 + max((len(x) for x in re.findall(r"`+", text)), default=0))
    return delimiter + "text\n" + text + "\n" + delimiter + "\n"


def _readme(draft: dict, packet: dict) -> bytes:
    label = (
        "SYNTHETIC: illustrative values, not actual weather."
        if packet["synthetic"]
        else "Local review only."
    )
    return (
        "# Private text and graphic review\n\n"
        + label
        + "\n\nScientific agreement: **UNREVIEWED**. Publication approved: **false**.\n\n"
        "This is a retained snapshot. It does not check the live draft, grant approval, "
        "or certify the sources. Verify the text, dates, units, comparison scope and "
        "source evidence together. PNG checks are structural, not a full image decoder.\n\n"
        "## Draft text\n\n"
        + _fence(draft["text"])
        + "\n## Graphic\n\n![Retained local graphic](preview.png)\n\n"
        "Open at full size to read the source and comparison qualifications.\n\n"
        "## Exact alt text\n\n"
        + _fence(packet["media"]["alt_text"])
        + "\nEvidence and retained bundle: `spec.json`. Exact draft: `draft.json`. "
        "Supplied policy: `policy.json`. Requested identity: `expected-identity.json`. "
        "Binding: `packet.json`. Asset provenance: `renderer-manifest.json`. "
        "Package byte hashes: `package.json`.\n"
    ).encode("utf-8")


def _git(repository: Path, arguments: list[str], *, data: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=data,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    _require(result.returncode == 0, "Repository or ignored-output verification failed")
    return result.stdout


def _check_ignored(repository: Path, output: Path, key: str, names: set[str]) -> None:
    _require(
        _git(repository, ["rev-parse", "--show-toplevel"]).strip() == str(repository),
        "Select the exact repository root",
    )
    paths = [
        str(output) + "/",
        str(output / ".prepare.lock"),
        str(output / ".staging-probe" / "draft.json"),
    ]
    paths += [str(output / key / name) for name in sorted(names)]
    ignored = _git(repository, ["check-ignore", "--stdin"], data="\n".join(paths) + "\n")
    _require(ignored.splitlines() == paths, "Every package file must be ignored by Git")


def _private_directory(fd: int) -> None:
    info = os.fstat(fd)
    _require(
        stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid(),
        "The package directory must be owned by this user with mode 0700",
    )


@contextmanager
def _output(repository: Path) -> Iterator[int]:
    with _directory(repository) as repo:
        try:
            os.mkdir(".gstack", 0o700, dir_fd=repo)
        except FileExistsError:
            pass
        gstack = os.open(".gstack", _DIRECTORY, dir_fd=repo)
        try:
            try:
                os.mkdir("media-review", 0o700, dir_fd=gstack)
            except FileExistsError:
                pass
            root = os.open("media-review", _DIRECTORY, dir_fd=gstack)
            try:
                _private_directory(root)
                yield root
            finally:
                os.close(root)
        finally:
            os.close(gstack)


@contextmanager
def _locked(root: int) -> Iterator[None]:
    fd = os.open(
        ".prepare.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root
    )
    try:
        info = os.fstat(fd)
        _require(
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1
            and info.st_uid == os.getuid(),
            "Unsafe package writer lock",
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MediaReviewError(
                "Another package writer is active; retry after it finishes"
            ) from None
        yield
    finally:
        os.close(fd)


def _verify(directory: int, files: dict[str, bytes]) -> None:
    _private_directory(directory)
    _require(set(os.listdir(directory)) == set(files), "Package file set changed or is incomplete")
    for name, data in files.items():
        _require(
            _read_at(directory, name, len(data), private=True) == data,
            "Package bytes changed; existing contents are never overwritten",
        )


def _write(directory: int, name: str, data: bytes) -> None:
    fd = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _install(root: int, key: str, files: dict[str, bytes]) -> bool:
    """Return whether an identical existing package was reused, under the lock."""
    try:
        existing = os.open(key, _DIRECTORY, dir_fd=root)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        try:
            _verify(existing, files)
            os.fsync(root)
            return True
        finally:
            os.close(existing)
    stage_name = ".staging-" + uuid.uuid4().hex
    os.mkdir(stage_name, 0o700, dir_fd=root)
    stage = os.open(stage_name, _DIRECTORY, dir_fd=root)
    installed = False
    try:
        for name, data in files.items():
            _write(stage, name, data)
        _verify(stage, files)
        os.fsync(stage)
        # Only cooperating writers can change this private root. They all hold
        # this lock; any pre-existing target (even empty) was refused above.
        os.rename(stage_name, key, src_dir_fd=root, dst_dir_fd=root)
        installed = True
        os.fsync(root)
        return False
    finally:
        try:
            if not installed:
                for name in os.listdir(stage):
                    os.unlink(name, dir_fd=stage)
                os.rmdir(stage_name, dir_fd=root)
        finally:
            os.close(stage)


def prepare_media_review(
    *,
    repository: Path,
    output_root: Path,
    draft_path: Path,
    expected_identity_path: Path,
    spec_path: Path,
    policy_path: Path,
    manifest_path: Path,
    pdftoppm: Path,
) -> dict:
    """Package explicit current inputs; never discover a draft, render or publish.

    The caller must obtain the requested identity and current policy independently
    of the preview/package. A supplied policy file is not checked against a live
    service. Reusing a package means identical bytes, never approval/currentness
    of a later live draft. All diagnostics deliberately omit caller payloads.
    """
    try:
        return _prepare(
            repository=repository,
            output_root=output_root,
            draft_path=draft_path,
            expected_identity_path=expected_identity_path,
            spec_path=spec_path,
            policy_path=policy_path,
            manifest_path=manifest_path,
            pdftoppm=pdftoppm,
        )
    except MediaReviewError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
        subprocess.SubprocessError,
    ):
        raise MediaReviewError(
            "Unsafe, unreadable, changed or malformed local review input/output"
        ) from None


def _prepare(**paths: Path) -> dict:
    paths = {key: _path(value) for key, value in paths.items()}
    repository, output = paths["repository"], paths["output_root"]
    _require(
        output == repository / ".gstack" / "media-review",
        "Output must be this repository's .gstack/media-review root",
    )
    # Validate ancestors even on paths later accessed through directory handles.
    with _directory(repository):
        pass
    draft, expected, spec, policy = (
        _json(_read(paths[key], MAX_JSON_BYTES))
        for key in ("draft_path", "expected_identity_path", "spec_path", "policy_path")
    )
    manifest_path = paths["manifest_path"]
    _require(manifest_path.name == "manifest.json", "Select the renderer's manifest.json")
    with _directory(manifest_path.parent) as preview:
        _require(
            set(os.listdir(preview)) == _ASSETS | {"manifest.json"},
            "Unexpected or incomplete preview asset set",
        )
        manifest = _json(_read_at(preview, "manifest.json", MAX_JSON_BYTES))
        _require(
            isinstance(manifest.get("files"), dict) and set(manifest["files"]) == _ASSETS,
            "Unexpected renderer asset names",
        )
        assets = {name: _read_at(preview, name, _LIMITS[name]) for name in sorted(_ASSETS)}
    for name, data in assets.items():
        _require(_digest(data) == manifest["files"][name], "Preview asset hash changed")
    packet = build_media_review_packet(
        draft,
        expected_draft_identity=expected,
        editorial_policy=policy,
        graphic_spec=spec,
        renderer_manifest=manifest,
        png_bytes=assets["preview.png"],
    )
    _check_renderer(manifest, paths["pdftoppm"])
    files = {
        **assets,
        "packet.json": _encode(packet),
        "draft.json": _encode(draft),
        "expected-identity.json": _encode(expected),
        "spec.json": _encode(spec),
        "policy.json": _encode(policy),
        "renderer-manifest.json": _encode(manifest),
        "README.md": _readme(draft, packet),
    }
    key = packet["packet_sha256"]
    files["package.json"] = _encode(
        {
            "schema_version": 1,
            "packet_sha256": key,
            "synthetic": packet["synthetic"],
            "claim_agreement_status": "unreviewed",
            "publication_approved": False,
            "files": {name: _digest(data) for name, data in files.items()},
        }
    )
    _check_ignored(repository, output, key, set(files))
    with _output(repository) as root, _locked(root):
        reused = _install(root, key, files)
    return {
        "output": str(output / key),
        "packet_sha256": key,
        "reused": reused,
        "synthetic": packet["synthetic"],
        "claim_agreement_status": "unreviewed",
        "publication_approved": False,
        "file_count": len(files),
    }
