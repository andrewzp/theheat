"""Offline sudo replacement for extracted CI steps. Never executes a command.

Only writes below a pytest-owned temporary root; all absolute workflow destinations
are translated there. Unknown commands fail rather than reaching a real binary.
"""
import json
import os
from pathlib import Path
import sys


root = Path(os.environ["THEHEAT_CI_STUB_ROOT"])
args = sys.argv[1:]
key = "/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc"
repository = "/etc/apt/sources.list.d/pgdg.list"
cluster = "/etc/postgresql-common/createcluster.conf"
ubuntu = "/etc/apt/sources.list.d/ubuntu.sources"
scoped = str(Path(os.environ["RUNNER_TEMP"]) / "theheat-test-apt-sources")


def destination(name):
    assert name in {key, repository, cluster, ubuntu, scoped,
                    scoped + "/ubuntu.sources", scoped + "/pgdg.list"}
    path = root / "filesystem" / name.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record(phase, **details):
    with (root / "calls.jsonl").open("a") as output:
        output.write(json.dumps({"phase": phase, "args": args, **details}) + "\n")
    if phase == os.environ.get("THEHEAT_CI_STUB_FAIL"):
        sys.exit(47)


if args[0] == "install":
    if args[1:] == ["-d", "/usr/share/postgresql-common/pgdg", "/etc/postgresql-common"]:
        record("directories")
    elif args[1:] == ["-d", scoped]:
        record("source_directory")
        destination(scoped).mkdir()
    else:
        assert args[1:3] == ["-m", "0644"] and len(args) == 5
        original, target = args[3:]
        assert (original, target) in {(ubuntu, scoped + "/ubuntu.sources"),
                                     (repository, scoped + "/pgdg.list")}
        record("source_ubuntu" if original == ubuntu else "source_postgres")
        if not destination(original).is_file():
            sys.exit(49)
        destination(target).write_bytes(destination(original).read_bytes())
elif args[0] == "curl":
    assert all(flag in args for flag in ("--fail", "--silent", "--show-error"))
    assert not any(flag in args for flag in ("--insecure", "-k", "--retry-all-errors"))
    for option, value in {
        "--connect-timeout": "10", "--max-time": "45", "--retry": "2",
        "--retry-max-time": "100", "-o": key,
    }.items():
        assert args[args.index(option) + 1] == value
    assert "https://www.postgresql.org/media/keys/ACCC4CF8.asc" in args
    record("key")
    destination(key).write_text("synthetic signing key\n")
elif args[0] == "tee":
    assert len(args) == 2 and args[1] in {repository, cluster}
    phase = "repository" if args[1] == repository else "cluster"
    record(phase)
    destination(args[1]).write_text(sys.stdin.read())
elif args[0] == "apt-get":
    # Parse options separately from the operation. No default retries/timeouts,
    # unsigned sources, quiet errors or alternate major version can pass this stub.
    options = {}
    rest = args[1:]
    while rest and rest[0] == "-o":
        name, value = rest[1].split("=", 1)
        assert name not in options
        options[name] = value
        rest = rest[2:]
    required = {
        "Acquire::Retries": "2", "Acquire::http::Timeout": "20",
        "Acquire::https::Timeout": "20",
    }
    # The old workflow remains representable for the red reproduction. Unknown
    # options still fail; omitting either scope override cannot masquerade as it.
    isolated = {**required, "Dir::Etc::sourcelist": "/dev/null", "Dir::Etc::sourceparts": scoped}
    assert options in (required, isolated)
    assert destination(key).read_text() == "synthetic signing key\n"
    assert destination(repository).read_text() == (
        f"deb [signed-by={key}] https://apt.postgresql.org/pub/repos/apt noble-pgdg main\n"
    )
    assert destination(cluster).read_text() == "create_main_cluster = false\n"
    parts = destination(scoped) if options == isolated else root / "filesystem/etc/apt/sources.list.d"
    sources = sorted(path.name for path in parts.iterdir() if path.suffix in {".list", ".sources"})
    if options == isolated:
        assert sources == ["pgdg.list", "ubuntu.sources"]
        assert destination(scoped + "/ubuntu.sources").read_bytes() == destination(ubuntu).read_bytes()
        assert destination(scoped + "/pgdg.list").read_bytes() == destination(repository).read_bytes()
    if rest == ["update", "--error-on=any"]:
        record("metadata", requested_sources=sources)
        if (root / "unrelated-repo-429").exists() and "microsoft-prod.list" in sources:
            sys.exit(100)
        (root / "metadata-ready").touch()
    else:
        assert rest[:3] == ["install", "-y", "--no-install-recommends"]
        assert rest[3:6] == ["postgresql-17", "postgresql-client-17", "poppler-utils"]
        assert rest[6:] in ([], ["gdb"])
        assert (root / "metadata-ready").exists()
        record("packages", requested_sources=sources)
        (root / "packages.json").write_text(json.dumps(rest[3:]))
else:
    raise AssertionError("Unrecognized dependency command; refusing execution")
