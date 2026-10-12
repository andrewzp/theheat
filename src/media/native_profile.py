"""Frozen local native dependencies with explicitly named OS-trusted libraries.

Capture inspects trusted installed binaries outside SQL. Verify hashes a frozen
inventory without loader subprocesses. This is not operating-system attestation.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

DISTRIBUTIONS = ("reportlab", "pillow", "charset-normalizer", "tzdata")
MAX_FILES, MAX_NATIVE, MAX_EDGES = 4096, 256, 1024
MAX_FILE, MAX_TOTAL, MAX_MANIFEST = 128 * 1024**2, 512 * 1024**2, 2 * 1024**2
ROOT = Path(__file__).resolve().parents[2]
LOCKS = (ROOT / "requirements-graphics.txt", ROOT / "dashboard/uv.lock")


def require(condition, reason):
    if not condition:
        raise ValueError("native_profile_" + reason)


def path(value):
    require(type(value) is str and 0 < len(value) <= 4096 and value.startswith("/")
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), "path")
    return Path(value)


def file_identity(filename):
    target = path(str(filename))
    before = target.stat()
    require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= MAX_FILE, "file_bound")
    digest, size = hashlib.sha256(), 0
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            require(size <= MAX_FILE, "file_bound")
            digest.update(chunk)
    after = target.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and size == before.st_size, "changed_during_read")
    return dict(sha256=digest.hexdigest(), bytes=size)


def platform_identity():
    uname = os.uname()
    require(uname.sysname in {"Darwin", "Linux"}, "unsupported_platform")
    identity = Path("/System/Library/CoreServices/SystemVersion.plist" if uname.sysname == "Darwin" else "/etc/os-release")
    return dict(system=uname.sysname, architecture=uname.machine, kernel_release=uname.release,
                kernel_version=uname.version, system_identity=file_identity(identity))


def installed_distributions():
    result = {}
    prefix = Path(sys.prefix).resolve()
    for name in DISTRIBUTIONS:
        dist = metadata.distribution(name)
        require(dist.files is not None, "missing_distribution_inventory")
        assert dist.files is not None
        rows = []
        for item in dist.files:
            if str(item).endswith(".pyc"):
                continue  # Child uses a fresh private bytecode directory.
            filename = Path(os.path.abspath(str(dist.locate_file(item))))
            require(filename.resolve().is_relative_to(prefix), "distribution_path")
            require(filename.is_file(), "distribution_file_missing")
            rows.append(str(filename))
        result[name] = dict(version=dist.version, files=sorted(set(rows)))
    require(sum(len(row["files"]) for row in result.values()) <= MAX_FILES, "distribution_count")
    return result


def macho_commands(output):
    dependencies, rpaths = [], []
    for block in re.split(r"(?m)^Load command \d+\n", output)[1:]:
        match = re.search(r"(?m)^\s+cmd (LC_[A-Z0-9_]+)\s*$", block)
        require(match is not None, "macho_command")
        assert match is not None
        kind = match[1]
        if kind in {"LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB", "LC_LOAD_UPWARD_DYLIB"}:
            value = re.search(r"(?m)^\s+name (.+) \(offset \d+\)\s*$", block)
            require(value is not None, "macho_reference")
            assert value is not None
            dependencies.append(value[1])
        elif kind == "LC_RPATH":
            value = re.search(r"(?m)^\s+path (.+) \(offset \d+\)\s*$", block)
            require(value is not None, "macho_rpath")
            assert value is not None
            rpaths.append(value[1])
    require("Load command 0\n" in output, "macho_output")
    return dependencies, rpaths


def expand(value, loader, executable):
    if value.startswith("@loader_path/"):
        return str(loader.parent / value.removeprefix("@loader_path/"))
    if value.startswith("@executable_path/"):
        return str(executable.parent / value.removeprefix("@executable_path/"))
    require(value.startswith("/"), "unsupported_loader_token")
    return value


def resolve_macho(reference, loader, executable, rpaths):
    if reference.startswith(("/usr/lib/", "/System/Library/")):
        require(str(path(reference)) == reference and os.path.normpath(reference) == reference, "system_reference")
        return None  # Named OS system/dyld-cache reference, never a byte proof.
    candidates = ([str(Path(directory) / reference.removeprefix("@rpath/")) for directory in rpaths]
                  if reference.startswith("@rpath/") else [expand(reference, loader, executable)])
    resolved = {path(item).resolve(strict=True) for item in candidates if path(item).is_file()}
    require(len(resolved) == 1, "missing_or_ambiguous_library")
    selected = next(iter(resolved))
    return selected, candidates


def linux_dependencies(output):
    result: list[tuple[str, str | None]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line == "statically linked":
            continue
        virtual = re.fullmatch(r"(linux-vdso\.so\.1|linux-gate\.so\.1) \(0x[0-9a-f]+\)", line)
        if virtual:
            result.append((virtual[1], None))
            continue
        match = re.fullmatch(r"(?:(\S+) => )?(/.+) \(0x[0-9a-f]+\)", line)
        require(match is not None, "unresolved_linux_dependency")
        assert match is not None
        result.append((match[1] or match[2], str(path(match[2]))))
    require(bool(result) or output.strip() == "statically linked", "linux_output")
    mappings: dict[str, str | None] = {}
    for name, target in result:
        require(name not in mappings or mappings[name] == target, "ambiguous_linux_dependency")
        mappings[name] = target
    return list(mappings.items())


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def symbolic_edges(filename):
    result = {}
    value = path(str(filename))
    for entry in (*reversed(value.parents), value):
        if entry.is_symlink():
            result[str(entry)] = os.readlink(entry)
    return result


def capture(rasterizer):
    started = time.monotonic()
    platform = platform_identity()
    distributions = installed_distributions()
    files, resolutions, edges, native_seen = {}, {}, [], set()
    symlinks, missing = {}, set()
    def retain(filename):
        logical = path(str(filename))
        symlinks.update(symbolic_edges(logical))
        resolved = logical.resolve(strict=True)
        resolutions[str(logical)] = str(resolved)
        if str(resolved) not in files:
            files[str(resolved)] = file_identity(resolved)
            require(len(files) <= MAX_FILES + MAX_NATIVE and sum(f["bytes"] for f in files.values()) <= MAX_TOTAL, "total_bound")
        require(time.monotonic() - started <= 60, "capture_timeout")
        return resolved
    # Invoke/bind the actual CLT tool, avoiding the OS developer-tool shim.
    tool = retain(Path("/Library/Developer/CommandLineTools/usr/bin/otool-classic") if platform["system"] == "Darwin" else Path("/usr/bin/ldd"))
    rasterizer, executable = retain(path(str(rasterizer))), retain(Path(sys.executable))
    roots = [(rasterizer, rasterizer), (executable, executable)]
    for row in distributions.values():
        for filename in row["files"]:
            retained = retain(filename)
            if filename.endswith((".so", ".dylib")):
                roots.append((retained, executable))
    for lock in LOCKS:
        retain(lock)
    queue = [(file, entry, ()) for file, entry in roots]
    while queue:
        filename, entry, inherited = queue.pop(0)
        key = (str(filename), str(entry), inherited)
        if key in native_seen:
            continue
        native_seen.add(key)
        require(len({item[0] for item in native_seen}) <= MAX_NATIVE, "native_count")
        args = [str(tool), "-arch", platform["architecture"], "-l", str(filename)] if platform["system"] == "Darwin" else [str(tool), str(filename)]
        remaining = 60 - (time.monotonic() - started)
        require(remaining > 0, "capture_timeout")
        run = subprocess.run(args, env={"PATH":"/usr/bin:/bin", "LC_ALL":"C"}, capture_output=True,
                             timeout=min(5, remaining), check=True)
        require(len(run.stdout) <= 256 * 1024 and len(run.stderr) <= 256 * 1024, "inspection_output_bound")
        output = run.stdout.decode("utf-8", errors="strict")
        if platform["system"] == "Darwin":
            names, own = macho_commands(output)
            rpaths = tuple(dict.fromkeys([expand(value, filename, entry) for value in own] + list(inherited)))
            for name in names:
                found = resolve_macho(name, filename, entry, rpaths)
                edge = dict(source=str(filename), reference=name, executable=str(entry))
                if found is None:
                    edge.update(os_trusted=True, resolved=None)
                else:
                    target, symbolic = found
                    for item in symbolic:
                        if Path(item).is_file():
                            retain(item)
                        else:
                            missing.add(item)
                    edge.update(os_trusted=False, resolved=str(target))
                    queue.append((target, entry, rpaths))
                if edge not in edges:
                    edges.append(edge)
        else:
            for name, found in linux_dependencies(output):
                edge = dict(source=str(filename), reference=name, executable=str(entry), os_trusted=found is None,
                            resolved=str(retain(found)) if found else None)
                if edge not in edges:
                    edges.append(edge)
                if found:
                    queue.append((Path(edge["resolved"]), entry, ()))
        require(len(edges) <= MAX_EDGES, "edge_count")
    manifest = dict(schema_version=1, platform=platform, distributions=distributions, files=files,
        resolutions=resolutions, native_edges=edges, inspection_tool=str(tool), rasterizer=str(rasterizer),
        symlinks=symlinks, missing_search_paths=sorted(missing),
        python_executable=str(executable), trust="named_os_libraries_are_os_trusted_not_byte_verified")
    require(len(encoded(manifest)) <= MAX_MANIFEST, "manifest_bound")
    verify(manifest, rasterizer=str(rasterizer))
    return manifest


def verify(manifest, *, rasterizer):
    require(type(manifest) is dict and set(manifest) == {
        "schema_version", "platform", "distributions", "files", "resolutions", "native_edges",
        "inspection_tool", "rasterizer", "symlinks", "missing_search_paths", "python_executable", "trust"}
            and type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1
            and len(encoded(manifest)) <= MAX_MANIFEST, "manifest_shape")
    require(manifest["trust"] == "named_os_libraries_are_os_trusted_not_byte_verified"
            and all(type(manifest[key]) is dict for key in ("files", "resolutions", "symlinks"))
            and type(manifest["native_edges"]) is list and type(manifest["missing_search_paths"]) is list, "manifest_shape")
    require(manifest["platform"] == platform_identity() and manifest["distributions"] == installed_distributions(), "runtime_changed")
    require(str(path(str(rasterizer)).resolve(strict=True)) == manifest["rasterizer"]
            and str(Path(sys.executable).resolve()) == manifest["python_executable"], "executable_changed")
    require(0 < len(manifest["files"]) <= MAX_FILES + MAX_NATIVE and len(manifest["native_edges"]) <= MAX_EDGES, "inventory_bound")
    for edge in manifest["native_edges"]:
        require(type(edge) is dict and set(edge) == {"source", "reference", "executable", "os_trusted", "resolved"}
                and type(edge["os_trusted"]) is bool and type(edge["reference"]) is str
                and edge["source"] in manifest["files"] and edge["executable"] in manifest["files"], "edge_shape")
        if edge["os_trusted"]:
            require(edge["resolved"] is None, "edge_shape")
            if manifest["platform"]["system"] == "Darwin":
                require(edge["reference"].startswith(("/usr/lib/", "/System/Library/"))
                        and os.path.normpath(str(path(edge["reference"]))) == edge["reference"], "system_reference")
            else:
                require(edge["reference"] in {"linux-vdso.so.1", "linux-gate.so.1"}, "system_reference")
        else:
            require(type(edge["resolved"]) is str and edge["resolved"] in manifest["files"], "incomplete_inventory")
    mandatory = [manifest["inspection_tool"], manifest["rasterizer"], manifest["python_executable"],
                 *map(str, LOCKS), *[name for row in manifest["distributions"].values() for name in row["files"]]]
    require(all(name in manifest["resolutions"] or name in manifest["files"] for name in mandatory), "incomplete_inventory")
    require(len(manifest["missing_search_paths"]) <= MAX_EDGES, "search_bound")
    for absent in manifest["missing_search_paths"]:
        require(not path(absent).exists(), "search_path_changed")
    total = 0
    symlinks = {}
    for logical, resolved in manifest["resolutions"].items():
        symlinks.update(symbolic_edges(logical))
        require(str(path(logical).resolve(strict=True)) == resolved and resolved in manifest["files"], "resolution_changed")
    require(symlinks == manifest["symlinks"], "symlink_changed")
    for filename, expected in manifest["files"].items():
        actual = file_identity(path(filename))
        require(actual == expected, "file_changed")
        total += actual["bytes"]
        require(total <= MAX_TOTAL, "total_bound")
    return hashlib.sha256(encoded(manifest)).hexdigest()


def load(filename, *, rasterizer):
    filename = path(str(filename))
    mode = filename.lstat()
    require(stat.S_ISREG(mode.st_mode) and mode.st_uid == os.getuid() and mode.st_mode & 0o077 == 0
            and 0 < mode.st_size <= MAX_MANIFEST, "private_manifest_required")
    raw = filename.read_bytes()
    require(len(raw) <= MAX_MANIFEST, "manifest_bound")
    value = json.loads(raw)
    require(encoded(value) == raw, "canonical_manifest_required")
    return value, verify(value, rasterizer=rasterizer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rasterizer", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    value = capture(args.rasterizer)
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded(value))
    print(json.dumps({"captured":True, "sha256":hashlib.sha256(encoded(value)).hexdigest(),
                      "files":len(value["files"]), "native_edges":len(value["native_edges"])}))


if __name__ == "__main__":
    main()
