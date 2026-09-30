"""Filesystem boundaries use synthetic bundles and structural, not rendered, PNGs."""

from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess

import pytest

from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media import review_package as package
from src.media.review_packet import MAX_JSON_BYTES, MediaReviewError
from tests import test_media_review_packet as packet_fixtures

seed = packet_fixtures.seed  # shared qualified synthetic fixture


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def local(tmp_path, seed):
    root = tmp_path.resolve() / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text(".gstack/\n")
    inputs = root / "selected-inputs"
    inputs.mkdir()
    data = deepcopy(seed)
    preview = inputs / "preview"
    preview.mkdir()
    binary = inputs / "rasterizer"
    binary.write_bytes(b"synthetic rasterizer fingerprint; never executable")
    media = Path(package.__file__).resolve().parent
    manifest = data["renderer_manifest"]
    renderer = manifest["binding"]["renderer"]
    for key, path in {
        "rasterizer_sha256": binary,
        "implementation_sha256": media / "evidence_graphic_render.py",
        "contract_sha256": media / "evidence_graphic.py",
        "adapter_sha256": media / "temperature_graphic_adapter.py",
        "font_sha256": media / "fonts" / "DejaVuSansMono.ttf",
    }.items():
        renderer[key] = digest(path.read_bytes())
    manifest["cache_key"] = fingerprint(manifest["binding"])
    assets = {
        "input.json": encode(data["graphic_spec"]),
        "preview.svg": b"synthetic svg",
        "preview.pdf": b"synthetic pdf",
        "preview.png": data["png_bytes"],
        "alt.txt": (manifest["alt_text"] + "\n").encode(),
    }
    for name, value in assets.items():
        (preview / name).write_bytes(value)
    (preview / "manifest.json").write_bytes(encode(manifest))
    paths = {
        "repository": root,
        "output_root": root / ".gstack" / "media-review",
        "manifest_path": preview / "manifest.json",
        "pdftoppm": binary,
    }
    for key, name in {
        "draft_path": "draft",
        "expected_identity_path": "expected_draft_identity",
        "spec_path": "graphic_spec",
        "policy_path": "editorial_policy",
    }.items():
        paths[key] = inputs / (key + ".json")
        paths[key].write_bytes(encode(data[name]))
    return paths


def snapshots(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def run(local):
    return package.prepare_media_review(**local)


def update_json(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.write_bytes(encode(value))


def stable_packages(root):
    return [p for p in root.glob("*") if not p.name.startswith(".")]


def test_exact_reuse_hashes_private_modes_and_no_external_io(local, monkeypatch):
    source = local["draft_path"].parent
    before = snapshots(source)
    original_run = package.subprocess.run

    def git_only(argv, **kwargs):
        assert argv[0] == "git" and argv[3] in {"rev-parse", "check-ignore"}
        return original_run(argv, **kwargs)

    monkeypatch.setattr(package.subprocess, "run", git_only)
    first = run(local)
    folder = Path(first["output"])
    saved = snapshots(folder)
    assert first["reused"] is False and first["file_count"] == 13
    assert (
        first["publication_approved"] is False and first["claim_agreement_status"] == "unreviewed"
    )
    assert first["synthetic"] is True
    second = run(local)
    assert second == {**first, "reused": True}
    assert snapshots(source) == before and snapshots(folder) == saved
    manifest = json.loads(saved["package.json"])
    assert {
        name: digest(data) for name, data in saved.items() if name != "package.json"
    } == manifest["files"]
    assert folder.name == json.loads(saved["packet.json"])["packet_sha256"]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in folder.iterdir())
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(folder.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize("change", ["text", "round_trip", "policy", "png", "svg", "pdf"])
def test_changed_bound_input_is_new_package(local, change):
    old = run(local)
    if change in {"text", "round_trip"}:
        draft = json.loads(local["draft_path"].read_bytes())
        original = draft["text"]
        invalidate_text(draft, "Changed synthetic comparison.")
        if change == "round_trip":
            invalidate_text(draft, original)
        local["draft_path"].write_bytes(encode(draft))
        local["expected_identity_path"].write_bytes(encode(draft_identity(draft)))
    elif change == "policy":
        update_json(local["policy_path"], lambda p: p.update(execution_sha256="a" * 64))
    else:
        name = "preview." + change
        path = local["manifest_path"].with_name(name)
        path.write_bytes(path.read_bytes() + b"different fixture bytes")
        update_json(
            local["manifest_path"],
            lambda m: m["files"].update({name: digest(path.read_bytes())}),
        )
    new = run(local)
    assert new["output"] != old["output"] and new["reused"] is False
    assert len(stable_packages(local["output_root"])) == 2


def test_stale_request_identity_refused(local):
    run(local)
    update_json(local["draft_path"], lambda d: invalidate_text(d, "Changed draft."))
    with pytest.raises(MediaReviewError, match="independent requested identity"):
        run(local)


def test_new_draft_evidence_requires_a_new_qualified_graphic(local):
    draft = json.loads(local["draft_path"].read_bytes())
    draft["review_context"]["two_bot"]["bundle"]["source_note"] = "new evidence"
    local["draft_path"].write_bytes(encode(draft))
    local["expected_identity_path"].write_bytes(encode(draft_identity(draft)))
    with pytest.raises(MediaReviewError, match="different retained bundles"):
        run(local)


@pytest.mark.parametrize("asset", sorted(package._ASSETS) + ["manifest.json"])
def test_tampered_preview_refused(local, asset):
    path = local["manifest_path"].with_name(asset)
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(MediaReviewError):
        run(local)
    assert not local["output_root"].exists()


@pytest.mark.parametrize("asset", ["input.json", "alt.txt"])
def test_manifest_and_asset_changed_together_still_require_exact_input(local, asset):
    path = local["manifest_path"].with_name(asset)
    path.write_bytes(path.read_bytes() + b"changed")
    update_json(
        local["manifest_path"], lambda m: m["files"].update({asset: digest(path.read_bytes())})
    )
    with pytest.raises(MediaReviewError):
        run(local)


@pytest.mark.parametrize(
    "field",
    [
        "implementation_sha256",
        "adapter_sha256",
        "font_sha256",
        "rasterizer_sha256",
        "contract_sha256",
    ],
)
def test_stale_renderer_provenance_refused_even_with_new_hash(local, field):
    def change(manifest):
        manifest["binding"]["renderer"][field] = "a" * 64
        manifest["cache_key"] = fingerprint(manifest["binding"])

    update_json(local["manifest_path"], change)
    with pytest.raises(MediaReviewError, match="renderer differs"):
        run(local)


@pytest.mark.parametrize("name", ["../secret", "/etc/passwd", "preview.png/other", "extra.txt"])
def test_manifest_asset_names_do_not_select_paths(local, name):
    update_json(local["manifest_path"], lambda m: m["files"].update({name: "a" * 64}))
    with pytest.raises(MediaReviewError, match="asset names"):
        run(local)


@pytest.mark.parametrize("kind", ["extra", "missing", "symlink", "fifo", "directory", "oversized"])
def test_preview_filesystem_anomalies_refused(local, kind):
    png = local["manifest_path"].with_name("preview.png")
    if kind == "extra":
        png.with_name("unexpected").write_bytes(b"x")
    elif kind == "oversized":
        with png.open("wb") as stream:
            stream.truncate(package.MAX_PNG_BYTES + 1)
    else:
        png.unlink()
        if kind == "symlink":
            png.symlink_to(local["pdftoppm"])
        elif kind == "fifo":
            os.mkfifo(png)
        elif kind == "directory":
            png.mkdir()
    with pytest.raises(MediaReviewError):
        run(local)


@pytest.mark.parametrize(
    "key", ["draft_path", "expected_identity_path", "spec_path", "policy_path", "manifest_path"]
)
@pytest.mark.parametrize(
    "bad",
    [
        b'{"x":1,"x":2}',
        b'{"nested":{"x":1,"x":2}}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b"\xff",
        b'{"x":"\\ud800"}',
        b"[]",
        b"{" + b" " * MAX_JSON_BYTES,
    ],
    # Pytest exports the case ID via PYTEST_CURRENT_TEST to fixture subprocesses.
    # Keep the one-megabyte payload out of that environment variable on Linux.
    ids=[
        "duplicate-key",
        "nested-duplicate-key",
        "nan",
        "infinity",
        "invalid-utf8",
        "lone-surrogate",
        "non-object",
        "oversized",
    ],
)
def test_json_input_limits_and_ambiguity(local, key, bad):
    local[key].write_bytes(bad)
    with pytest.raises(MediaReviewError):
        run(local)
    assert not local["output_root"].exists()


@pytest.mark.parametrize("key", ["draft_path", "pdftoppm", "manifest_path"])
def test_input_symlink_and_ancestor_refused(local, key):
    path = local[key]
    real = path.with_name(path.name + "-real")
    path.rename(real)
    path.symlink_to(real)
    with pytest.raises(MediaReviewError):
        run(local)
    path.unlink()
    real.rename(path)
    alias = path.parent.with_name("alias")
    alias.symlink_to(path.parent, target_is_directory=True)
    local[key] = alias / path.name
    with pytest.raises(MediaReviewError):
        run(local)


@pytest.mark.parametrize(
    "key", ["repository", "output_root", "draft_path", "manifest_path", "pdftoppm"]
)
@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/input",
        "relative.json",
        "/tmp/../tmp/input",
        "//server/share",
        "/tmp/bad\nname",
    ],
)
def test_nonlocal_or_ambiguous_paths_refused(local, key, value):
    local[key] = Path(value)
    with pytest.raises(MediaReviewError):
        run(local)


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_root",
        "unignored",
        "partly_unignored",
        "symlink_gstack",
        "symlink_output",
        "public_output",
    ],
)
def test_output_containment(local, kind):
    root = local["repository"]
    if kind == "wrong_root":
        local["output_root"] = root / "outside"
    elif kind == "unignored":
        (root / ".gitignore").write_text("")
    elif kind == "partly_unignored":
        (root / ".gitignore").write_text(
            ".gstack/**\n!.gstack/media-review/\n!.gstack/media-review/*/\n!.gstack/media-review/*/draft.json\n"
        )
    elif kind == "symlink_gstack":
        (root / ".gstack").symlink_to(root / "selected-inputs", target_is_directory=True)
    else:
        (root / ".gstack").mkdir()
        if kind == "symlink_output":
            local["output_root"].symlink_to(root / "selected-inputs", target_is_directory=True)
        else:
            local["output_root"].mkdir(mode=0o755)
    with pytest.raises(MediaReviewError):
        run(local)


@pytest.mark.parametrize(
    "kind",
    [
        "bytes",
        "extra",
        "missing",
        "symlink",
        "hardlink",
        "file_mode",
        "folder_mode",
        "symlink_package",
        "empty",
    ],
)
def test_existing_tampering_is_never_overwritten(local, kind):
    result = run(local)
    folder = Path(result["output"])
    draft = folder / "draft.json"
    if kind == "bytes":
        draft.write_bytes(b"changed")
    elif kind == "extra":
        (folder / "extra").write_bytes(b"extra")
    elif kind == "file_mode":
        draft.chmod(0o644)
    elif kind == "folder_mode":
        folder.chmod(0o755)
    elif kind == "symlink_package":
        moved = folder.with_name(".original")
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
    elif kind == "empty":
        for child in folder.iterdir():
            child.unlink()
    else:
        draft.unlink()
        if kind == "symlink":
            draft.symlink_to(local["draft_path"])
        elif kind == "hardlink":
            local["draft_path"].chmod(0o600)
            os.link(local["draft_path"], draft)
    before = snapshots(local["output_root"])
    with pytest.raises(MediaReviewError):
        run(local)
    assert snapshots(local["output_root"]) == before


@pytest.mark.parametrize("position", range(13))
def test_failure_at_each_staged_write_leaves_no_final_package(local, monkeypatch, position):
    write = package._write
    calls = 0

    def fail(directory, name, data):
        nonlocal calls
        write(directory, name, data[:3] if calls == position else data)
        calls += 1
        if calls == position + 1:
            raise OSError("simulated disk failure")

    with monkeypatch.context() as m:
        m.setattr(package, "_write", fail)
        with pytest.raises(MediaReviewError):
            run(local)
    assert not stable_packages(local["output_root"])
    assert not list(local["output_root"].glob(".staging-*"))
    assert run(local)["reused"] is False


def _crash_during_write(local):
    original = package._write

    def crash(directory, name, data):
        original(directory, name, data)
        os._exit(73)

    package._write = crash
    run(local)


def test_abrupt_process_exit_leaves_only_hidden_stage_and_retry_succeeds(local):
    child = multiprocessing.get_context("fork").Process(target=_crash_during_write, args=(local,))
    child.start()
    child.join(10)
    assert child.exitcode == 73
    assert not stable_packages(local["output_root"])
    stages = list(local["output_root"].glob(".staging-*"))
    assert len(stages) == 1
    assert run(local)["reused"] is False
    assert stages[0].is_dir()  # preserve crashed staging evidence; never treat it as complete


def test_concurrent_writer_lock_refuses_and_then_recovers(local):
    run(local)
    with package._directory(local["output_root"]) as root, package._locked(root):
        with pytest.raises(MediaReviewError, match="Another package writer"):
            run(local)
    assert run(local)["reused"] is True


@pytest.mark.parametrize("boundary", ["verification", "rename", "file_sync", "parent_sync"])
def test_atomic_install_failure_boundaries(local, monkeypatch, boundary):
    if boundary == "verification":
        original = package._verify

        def reject(directory, files):
            original(directory, files)
            raise OSError("simulated verification failure")

        target, method, replacement = package, "_verify", reject
    elif boundary == "rename":

        def reject(*args, **kwargs):
            raise OSError("simulated rename failure")

        target, method, replacement = package.os, "rename", reject
    else:
        original = os.fsync
        calls = 0

        def reject(fd):
            nonlocal calls
            calls += 1
            # Thirteen files, staged directory, then the renamed package's parent.
            if calls == (1 if boundary == "file_sync" else 15):
                raise OSError("simulated sync failure")
            original(fd)

        target, method, replacement = package.os, "fsync", reject
    with monkeypatch.context() as m:
        m.setattr(target, method, replacement)
        with pytest.raises(MediaReviewError):
            run(local)
    # A failure after rename may leave the complete package, never partial bytes.
    assert len(stable_packages(local["output_root"])) == (1 if boundary == "parent_sync" else 0)
    result = run(local)
    assert result["reused"] is (boundary == "parent_sync")


def test_assets_are_not_read_again_after_validation(local, monkeypatch):
    original = package._check_renderer

    def change_cache_after_validation(*args):
        original(*args)
        local["manifest_path"].with_name("preview.png").write_bytes(b"changed later")

    png = local["manifest_path"].with_name("preview.png").read_bytes()
    monkeypatch.setattr(package, "_check_renderer", change_cache_after_validation)
    folder = Path(run(local)["output"])
    assert (folder / "preview.png").read_bytes() == png


def test_unbound_snapshot_changes_cannot_overwrite_same_packet(local):
    first = run(local)
    before = snapshots(Path(first["output"]))
    update_json(local["draft_path"], lambda d: d.update(private_note="new metadata"))
    with pytest.raises(MediaReviewError):
        run(local)
    assert snapshots(Path(first["output"])) == before


def test_cli_success_bounded_failure_and_inert_draft_markdown(local, capsys):
    from scripts.prepare_media_review import main

    draft = json.loads(local["draft_path"].read_bytes())
    draft["text"] = "```\n![remote](https://example.com/private)\n<script>alert(1)</script>\n```"
    local["draft_path"].write_bytes(encode(draft))
    local["expected_identity_path"].write_bytes(encode(draft_identity(draft)))
    flags = {
        "repository": "repository",
        "output_root": "output-root",
        "draft_path": "draft",
        "expected_identity_path": "expected-identity",
        "spec_path": "spec",
        "policy_path": "policy",
        "manifest_path": "manifest",
        "pdftoppm": "pdftoppm",
    }
    argv = [item for key, flag in flags.items() for item in ("--" + flag, str(local[key]))]
    assert main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    readme = (Path(result["output"]) / "README.md").read_text()
    assert "````text\n" + draft["text"] + "\n````" in readme
    assert readme.count("![Retained local graphic](preview.png)") == 1
    local["policy_path"].write_bytes(b"secret malformed content")
    assert main(argv) == 2
    captured = capsys.readouterr()
    assert "refused" in captured.err and "secret" not in captured.err
