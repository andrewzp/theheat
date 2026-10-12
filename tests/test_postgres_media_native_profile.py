"""Local installed-runtime evidence and explicit parser/refusal boundaries."""

from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace
import os
import signal
import subprocess
import sys
import time

import pytest

from src.media import native_profile as profile
from src.commands.preview_media_worker import run_native
from tests.native_profile_helpers import native_dependencies as native_dependencies


def test_actual_capture_and_verification_never_inspects_loaders_under_lock(
    native_dependencies, monkeypatch
):
    manifest, digest = profile.load(
        **dict(
            filename=native_dependencies["dependency_manifest"],
            rasterizer=native_dependencies["rasterizer"],
        )
    )
    assert len(manifest["files"]) > 100
    assert manifest["native_edges"] and any(edge["os_trusted"] for edge in manifest["native_edges"])
    assert manifest["trust"] == "named_os_libraries_are_os_trusted_not_byte_verified"
    monkeypatch.setattr(
        profile.subprocess, "run", lambda *a, **k: pytest.fail("Verify must not inspect a loader")
    )
    assert profile.verify(manifest, rasterizer=native_dependencies["rasterizer"]) == digest


@pytest.mark.parametrize(
    "changed",
    ["python_package", "native_library", "lock", "os", "symlink", "missing", "inventory", "bounds"],
)
def test_declared_dependency_drift_refuses_without_touching_installed_files(
    native_dependencies, monkeypatch, changed
):
    manifest, _ = profile.load(
        filename=native_dependencies["dependency_manifest"],
        rasterizer=native_dependencies["rasterizer"],
    )
    original = profile.file_identity
    if changed in {"python_package", "native_library", "lock", "missing"}:
        if changed == "python_package":
            target = manifest["distributions"]["reportlab"]["files"][0]
        elif changed == "lock":
            target = str(profile.LOCKS[0])
        else:
            target = next(
                edge["resolved"] for edge in manifest["native_edges"] if not edge["os_trusted"]
            )
        target = str(Path(target).resolve())

        def drift(filename):
            if str(filename) == target:
                if changed == "missing":
                    raise FileNotFoundError("invented missing installed dependency")
                return {**original(filename), "sha256": "f" * 64}
            return original(filename)

        monkeypatch.setattr(profile, "file_identity", drift)
    elif changed == "os":
        actual = profile.platform_identity()
        monkeypatch.setattr(
            profile, "platform_identity", lambda: {**actual, "kernel_release": "changed"}
        )
    elif changed == "symlink":
        manifest["symlinks"]["/invented/link"] = "changed"
    elif changed == "inventory":
        manifest["files"].pop(next(iter(manifest["files"])))
    else:
        monkeypatch.setattr(profile, "MAX_TOTAL", 1)
    with pytest.raises((ValueError, FileNotFoundError)):
        profile.verify(manifest, rasterizer=native_dependencies["rasterizer"])


@pytest.mark.parametrize("failure", [False, True])
def test_capture_diagnostics_preserve_subprocess_and_original_failure(monkeypatch, capsys, failure):
    from tests.native_profile_helpers import capture_with_diagnostics
    original = profile.subprocess
    argv = ["/usr/bin/ldd", "/invented/renderer-extension.so"]
    options = dict(env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                   capture_output=True, timeout=5, check=True)
    observed = []
    response = subprocess.CompletedProcess(argv, 0, b"libfixture.so => not found\n", b"")

    def run(*args, **kwargs):
        observed.append((args, kwargs))
        return response

    error = ValueError("native_profile_unresolved_linux_dependency")

    def capture(executable):
        assert executable == "/invented/pdftoppm"
        assert profile.subprocess.run(argv, **options) is response
        if failure:
            raise error
        return {"invented": "manifest"}

    monkeypatch.setattr(original, "run", run)
    monkeypatch.setattr(profile, "capture", capture)
    if failure:
        with pytest.raises(ValueError) as raised:
            capture_with_diagnostics("/invented/pdftoppm")
        assert raised.value is error
        line = capsys.readouterr().out.strip()
        assert line.startswith("NATIVE_CAPTURE_LAST_INSPECTION=")
        assert json.loads(line.split("=", 1)[1]) == dict(argv=argv, returncode=0,
            stdout="libfixture.so => not found\n", stderr="", stdout_bytes=27, stderr_bytes=0)
    else:
        assert capture_with_diagnostics("/invented/pdftoppm") == {"invented": "manifest"}
        assert capsys.readouterr().out == ""
    assert observed == [((argv,), options)]
    assert profile.subprocess is original


def test_capture_diagnostics_bound_last_output_and_restore_on_failure(monkeypatch, capsys):
    from tests.native_profile_helpers import capture_with_diagnostics
    original = profile.subprocess
    response = SimpleNamespace(returncode=0, stdout=b"x" * (256 * 1024 + 1), stderr=b"y" * (256 * 1024 + 1))
    monkeypatch.setattr(original, "run", lambda *args, **kwargs: response)

    def capture(executable):
        profile.subprocess.run(["/usr/bin/ldd", "/invented/earlier.so"])
        profile.subprocess.run(["/usr/bin/ldd", "/invented/last.so"])
        raise ValueError("native_profile_inspection_output_bound")

    monkeypatch.setattr(profile, "capture", capture)
    with pytest.raises(ValueError, match="native_profile_inspection_output_bound"):
        capture_with_diagnostics("/invented/pdftoppm")
    row = json.loads(capsys.readouterr().out.strip().split("=", 1)[1])
    assert row["argv"] == ["/usr/bin/ldd", "/invented/last.so"]
    assert row["stdout"] == "x" * (256 * 1024) and row["stderr"] == "y" * (256 * 1024)
    assert row["stdout_bytes"] == row["stderr_bytes"] == 256 * 1024 + 1
    assert profile.subprocess is original


def test_macho_declared_resolution_refuses_missing_ambiguous_and_unsupported(tmp_path):
    root = tmp_path / "bin"
    root.mkdir()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for folder in (a, b):
        (folder / "lib.so").write_bytes(b"invented")
    binary = root / "rasterizer"
    assert profile.resolve_macho("@loader_path/../a/lib.so", binary, binary, ())[0] == a / "lib.so"
    assert profile.resolve_macho("/usr/lib/libSystem.B.dylib", binary, binary, ()) is None
    for reference, paths in [
        ("@rpath/lib.so", (str(a), str(b))),
        ("@rpath/missing", (str(a),)),
        ("@unsupported/lib.so", ()),
        ("/usr/lib/../../private/foreign", ()),
    ]:
        with pytest.raises(ValueError):
            profile.resolve_macho(reference, binary, binary, paths)
    text = """invented:
Load command 0
          cmd LC_LOAD_DYLIB
         name @loader_path/lib.so (offset 24)
Load command 1
          cmd LC_RPATH
         path @executable_path/../lib (offset 12)
"""
    assert profile.macho_commands(text) == (["@loader_path/lib.so"], ["@executable_path/../lib"])
    with pytest.raises(ValueError):
        profile.macho_commands("unrecognized")


@pytest.mark.parametrize("changed", ["version", "extra", "trust", "missing_dependency", "false_system"])
def test_manifest_shape_and_dependency_edges_refuse_corruption(native_dependencies, changed):
    manifest, _ = profile.load(filename=native_dependencies["dependency_manifest"],
                               rasterizer=native_dependencies["rasterizer"])
    if changed == "version":
        manifest["schema_version"] = True
    elif changed == "extra":
        manifest["unreviewed"] = True
    elif changed == "trust":
        manifest["trust"] = "complete_os_attestation"
    else:
        edge = next(edge for edge in manifest["native_edges"] if not edge["os_trusted"])
        if changed == "missing_dependency":
            edge["resolved"] = "/invented/missing/dependency"
        else:
            edge.update(os_trusted=True, resolved=None, reference="/invented/system/library")
    with pytest.raises(ValueError):
        profile.verify(manifest, rasterizer=native_dependencies["rasterizer"])


@pytest.mark.parametrize(
    "text",
    [
        "libbad.so => not found",
        "unknown output",
        "linux-secret.so.1 (0x123)",
        "liba.so => /one (0x123)\nliba.so => /two (0x456)",
    ],
)
def test_linux_parser_refuses_unresolved_or_ambiguous_output(text):
    with pytest.raises(ValueError):
        profile.linux_dependencies(text)


def test_linux_declared_virtual_os_and_exact_real_paths():
    assert profile.linux_dependencies(
        "linux-vdso.so.1 (0xabc)\nlibc.so.6 => /lib/libc.so.6 (0xabc)\n/lib64/ld-linux-x86-64.so.2 (0xdef)"
    ) == [
        ("linux-vdso.so.1", None),
        ("libc.so.6", "/lib/libc.so.6"),
        ("/lib64/ld-linux-x86-64.so.2", "/lib64/ld-linux-x86-64.so.2"),
    ]


def test_private_manifest_rejects_permissions_noncanonical_and_symlink(
    native_dependencies, tmp_path
):
    raw = Path(native_dependencies["dependency_manifest"]).read_bytes()
    file = tmp_path / "profile.json"
    file.write_bytes(raw)
    file.chmod(0o644)
    with pytest.raises(ValueError):
        profile.load(file, rasterizer=native_dependencies["rasterizer"])
    file.chmod(0o600)
    file.write_bytes(raw + b"\n")
    with pytest.raises(ValueError):
        profile.load(file, rasterizer=native_dependencies["rasterizer"])
    alias = tmp_path / "symlink.json"
    alias.symlink_to(native_dependencies["dependency_manifest"])
    with pytest.raises(ValueError):
        profile.load(alias, rasterizer=native_dependencies["rasterizer"])


def test_outer_timeout_terminates_owned_descendant_even_when_it_ignores_term(tmp_path):
    pidfile = tmp_path / "descendant.pid"
    child = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
    parent = "import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c',sys.argv[2]]);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(30)"
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_native(
            [sys.executable, "-c", parent, str(pidfile), child],
            input=b"",
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            timeout=0.5,
            grace=0.5,
        )
    assert time.monotonic() - started < 3
    pid = int(pidfile.read_text())
    # This descendant is orphaned; init owns final waitpid. It must be dead,
    # including a briefly observable zombie, never running after our timeout.
    for _ in range(20):
        result = subprocess.run(
            ["/bin/ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
        )
        if result.returncode or result.stdout.strip().startswith("Z"):
            break
        time.sleep(0.05)
    else:
        os.kill(pid, signal.SIGKILL)
        pytest.fail("Owned renderer descendant survived timeout cleanup")


@pytest.fixture
def linux_loader_context(tmp_path, monkeypatch):
    """Invented loader output with real files; this does not emulate Linux ELF."""
    from types import SimpleNamespace

    names = ("ldd", "pdftoppm", "python", "_imaging.fixture.so", "libtiff.so.6", "libjpeg.so.62", "libsystem.so.6", "lock")
    files = {name: tmp_path / name for name in names}
    for name, filename in files.items():
        filename.write_bytes(("invented " + name).encode())
    alias = tmp_path / "libjpeg-link.so.62"
    alias.symlink_to(files["libjpeg.so.62"])
    roots = [files[name] for name in ("pdftoppm", "python", "_imaging.fixture.so")]
    outputs = {str(root): f"linux-vdso.so.1 (0xabc)\nlibsystem.so.6 => {files['libsystem.so.6']} (0xdef)\n" for root in roots}
    outputs[str(roots[2])] += f"libtiff.so.6 => {files['libtiff.so.6']} (0xa)\nlibjpeg.so.62 => {alias} (0xb)\n"
    calls = []

    def inspect(argv, **options):
        assert argv[0] == str(files["ldd"])
        assert argv[1] in outputs, "A resolved child must not become a standalone loader root"
        assert options == dict(env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, capture_output=True, timeout=5, check=True)
        calls.append(argv[1])
        return subprocess.CompletedProcess(argv, 0, outputs[argv[1]].encode(), b"")

    original_path = profile.Path
    monkeypatch.setattr(profile, "Path", lambda value: files["ldd"] if str(value) == "/usr/bin/ldd" else original_path(value))
    monkeypatch.setattr(profile, "sys", SimpleNamespace(executable=str(files["python"])))
    monkeypatch.setattr(profile, "subprocess", SimpleNamespace(run=inspect))
    monkeypatch.setattr(profile, "platform_identity", lambda: dict(system="Linux", architecture="invented", kernel_release="fixture", kernel_version="fixture", system_identity={"sha256": "a" * 64, "bytes": 1}))
    monkeypatch.setattr(profile, "installed_distributions", lambda: {"pillow": dict(version="fixture", files=[str(files[name]) for name in ("_imaging.fixture.so", "libtiff.so.6", "libjpeg.so.62")])})
    monkeypatch.setattr(profile, "LOCKS", (files["lock"],))
    return dict(files=files, alias=alias, roots=roots, outputs=outputs, calls=calls)


def test_linux_root_closure_retains_transitive_files_without_reopening_children(linux_loader_context):
    case = linux_loader_context
    manifest = profile.capture(str(case["files"]["pdftoppm"]))
    assert case["calls"] == [str(root) for root in case["roots"]]
    for name in ("libtiff.so.6", "libjpeg.so.62", "libsystem.so.6"):
        filename = case["files"][name]
        assert manifest["files"][str(filename)] == profile.file_identity(filename)
    assert manifest["symlinks"][str(case["alias"])] == str(case["files"]["libjpeg.so.62"])
    assert manifest["resolutions"][str(case["alias"])] == str(case["files"]["libjpeg.so.62"])
    assert any(edge["source"] == str(case["roots"][2]) and edge["resolved"] == str(case["files"]["libjpeg.so.62"])
               for edge in manifest["native_edges"])
    # Verification hashes the actual transitive target; no loader is rerun.
    case["files"]["libjpeg.so.62"].write_bytes(b"invented changed transitive bytes")
    with pytest.raises(ValueError, match="native_profile_file_changed"):
        profile.verify(manifest, rasterizer=str(case["files"]["pdftoppm"]))
    assert case["calls"] == [str(root) for root in case["roots"]]


def test_linux_root_closure_rejects_changed_transitive_symlink(linux_loader_context):
    case = linux_loader_context
    manifest = profile.capture(str(case["files"]["pdftoppm"]))
    case["alias"].unlink()
    case["alias"].symlink_to(case["files"]["libsystem.so.6"])
    with pytest.raises(ValueError, match="native_profile_resolution_changed"):
        profile.verify(manifest, rasterizer=str(case["files"]["pdftoppm"]))


@pytest.mark.parametrize("root", ["pdftoppm", "python", "_imaging.fixture.so"])
@pytest.mark.parametrize("failure", ["unresolved", "ambiguous"])
def test_linux_every_real_root_keeps_strict_dependency_refusal(linux_loader_context, root, failure):
    case = linux_loader_context
    case["outputs"][str(case["files"][root])] = (
        "libmissing.so => not found\n" if failure == "unresolved" else
        f"libsame.so => {case['files']['libtiff.so.6']} (0xa)\nlibsame.so => {case['files']['libjpeg.so.62']} (0xb)\n"
    )
    with pytest.raises(ValueError, match="native_profile_(?:unresolved|ambiguous)_linux_dependency"):
        profile.capture(str(case["files"]["pdftoppm"]))


@pytest.mark.parametrize("bound", [5, 6])
def test_linux_native_bound_counts_real_roots_and_transitive_targets(linux_loader_context, monkeypatch, bound):
    case = linux_loader_context
    monkeypatch.setattr(profile, "MAX_NATIVE", bound)
    # Three roots plus three distinct native targets. The inspection tool,
    # duplicate edges, virtual vDSO and symlink aliases are not extra binaries.
    if bound == 5:
        with pytest.raises(ValueError, match="native_profile_native_count"):
            profile.capture(str(case["files"]["pdftoppm"]))
    else:
        assert profile.capture(str(case["files"]["pdftoppm"]))["native_edges"]
