"""Bounded local file boundary for the offline evaluation command-line tools.

Every path is walked from "/" one component at a time through O_NOFOLLOW
directory descriptors, so no ancestor or leaf symlink is followed and a checked
parent cannot be swapped between the check and the open. Reads are nonblocking,
regular-file-only and bounded, so a FIFO without a writer or a device is refused
promptly. Follows the accepted descriptor pattern in src/media/review_package.py;
only the rainfall and readiness tools use this module.
"""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
import stat
from typing import Iterator

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class FileBoundaryError(ValueError):
    """A refused path; carries one fixed code, never the path or its contents."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise FileBoundaryError(code)


def _components(path: str) -> tuple[list[str], str]:
    _require(type(path) is str and 0 < len(path) <= 4096 and all(ord(ch) >= 32 for ch in path), "invalid_path")
    raw = path if path.startswith("/") else os.getcwd().rstrip("/") + "/" + path
    _require(not raw.startswith("//") and ".." not in raw.split("/"), "invalid_path")
    parts = [part for part in raw.split("/")[1:] if part not in {"", "."}]
    _require(bool(parts), "invalid_path")
    return parts[:-1], parts[-1]


def _refusal(exc: OSError, directory: int, name: str) -> FileBoundaryError | None:
    if exc.errno == errno.ELOOP:
        return FileBoundaryError("symlinked_path")
    if exc.errno == errno.ENOTDIR:
        try:
            is_link = stat.S_ISLNK(os.lstat(name, dir_fd=directory).st_mode)
        except OSError:
            is_link = False
        return FileBoundaryError("symlinked_path" if is_link else "not_a_directory")
    if exc.errno == errno.ENOENT:
        return FileBoundaryError("path_not_found")
    return None


def _open_directory(directory: int, name: str) -> int:
    try:
        return os.open(name, _DIRECTORY, dir_fd=directory)
    except OSError as exc:
        refusal = _refusal(exc, directory, name)
        if refusal is None:
            raise
        raise refusal from None


@contextmanager
def _directory(parts: list[str]) -> Iterator[int]:
    """Walk from / without ever following a directory symlink."""
    fd = os.open("/", _DIRECTORY)
    try:
        for component in parts:
            child = _open_directory(fd, component)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read_at(directory: int, name: str, limit: int) -> bytes:
    try:
        fd = os.open(name, _READ, dir_fd=directory)
    except OSError as exc:
        refusal = _refusal(exc, directory, name)
        if refusal is None:
            raise
        raise refusal from None
    try:
        # Checked on the descriptor before any read: a FIFO, device or directory never blocks or is read.
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode), "input_not_regular")
        _require(before.st_size <= limit, "input_too_large")
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "rb", buffering=0) as stream:
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining > 0:
            chunk = stream.read(min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
    _require(len(data) <= limit, "input_too_large")
    _require((before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
             == (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino)
             and len(data) == before.st_size, "input_changed")
    return data


def read_regular(path: str, limit: int) -> bytes:
    """Bounded bytes of one regular file reached without following any symlink."""
    parents, name = _components(path)
    with _directory(parents) as directory:
        return _read_at(directory, name, limit)
