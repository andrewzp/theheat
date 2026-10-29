"""Anchored no-follow, nonblocking, bounded file boundary for the offline CLIs.

Every path below is a task-owned invented file under pytest's temporary
directory, except the system null device used as the device case.
"""

import os

import pytest

from src.evaluation import file_boundary as boundary


@pytest.fixture
def root(tmp_path):
    base = tmp_path.resolve()
    (base / "a").mkdir()
    (base / "a" / "target.json").write_bytes(b'{"invented": "original"}')
    (base / "evil").mkdir()
    (base / "evil" / "target.json").write_bytes(b'{"invented": "attacker"}')
    return base


def test_reads_a_bounded_regular_file(root):
    assert boundary.read_regular(str(root / "a" / "target.json"), 64) == b'{"invented": "original"}'
    with pytest.raises(boundary.FileBoundaryError, match="input_too_large"):
        boundary.read_regular(str(root / "a" / "target.json"), 4)


def test_relative_paths_resolve_from_the_working_directory(root, monkeypatch):
    monkeypatch.chdir(root)
    assert boundary.read_regular("a/target.json", 64).startswith(b"{")
    with pytest.raises(boundary.FileBoundaryError, match="invalid_path"):
        boundary.read_regular("a/../a/target.json", 64)


@pytest.mark.parametrize("kind", ["fifo", "directory", "device"])
def test_fifo_directory_and_device_are_refused_without_blocking(root, kind):
    if kind == "fifo":
        target = root / "writerless.fifo"
        os.mkfifo(target)  # no writer: a blocking open would hang
    elif kind == "directory":
        target = root / "a"
    else:
        target = "/dev/null"
    with pytest.raises(boundary.FileBoundaryError, match="input_not_regular"):
        boundary.read_regular(str(target), 64)


def test_static_leaf_and_ancestor_symlinks_are_refused(root):
    (root / "leaf.json").symlink_to(root / "a" / "target.json")
    (root / "linked").symlink_to(root / "a")
    for path in (root / "leaf.json", root / "linked" / "target.json"):
        with pytest.raises(boundary.FileBoundaryError, match="symlinked_path"):
            boundary.read_regular(str(path), 64)
    with pytest.raises(boundary.FileBoundaryError, match="path_not_found"):
        boundary.read_regular(str(root / "a" / "absent.json"), 64)
    with pytest.raises(boundary.FileBoundaryError, match="not_a_directory"):
        boundary.read_regular(str(root / "a" / "target.json" / "child"), 64)


def test_checked_parent_replaced_before_the_open_cannot_redirect_the_read(root, monkeypatch):
    """The parent is held as a descriptor; swapping its path for a symlink changes nothing."""
    real = boundary._read_at

    def swap_then_read(directory, name, limit):
        os.rename(root / "a", root / "a-moved")
        (root / "a").symlink_to(root / "evil")
        return real(directory, name, limit)

    monkeypatch.setattr(boundary, "_read_at", swap_then_read)
    assert boundary.read_regular(str(root / "a" / "target.json"), 64) == b'{"invented": "original"}'
