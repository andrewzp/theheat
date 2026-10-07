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


def destination(name):
    assert name in {key, repository, cluster}
    path = root / "filesystem" / name.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record(phase):
    with (root / "calls.jsonl").open("a") as output:
        output.write(json.dumps({"phase": phase, "args": args}) + "\n")
    if phase == os.environ.get("THEHEAT_CI_STUB_FAIL"):
        sys.exit(47)


if args[0] == "install":
    assert args[1:] == ["-d", "/usr/share/postgresql-common/pgdg", "/etc/postgresql-common"]
    record("directories")
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
    assert options == {
        "Acquire::Retries": "2", "Acquire::http::Timeout": "20",
        "Acquire::https::Timeout": "20",
    }
    assert destination(key).read_text() == "synthetic signing key\n"
    assert destination(repository).read_text() == (
        f"deb [signed-by={key}] https://apt.postgresql.org/pub/repos/apt noble-pgdg main\n"
    )
    assert destination(cluster).read_text() == "create_main_cluster = false\n"
    if rest == ["update", "--error-on=any"]:
        record("metadata")
        (root / "metadata-ready").touch()
    else:
        assert rest == ["install", "-y", "--no-install-recommends", "postgresql-17", "postgresql-client-17"]
        assert (root / "metadata-ready").exists()
        record("packages")
        (root / "packages.json").write_text(json.dumps(rest[-2:]))
else:
    raise AssertionError("Unrecognized dependency command; refusing execution")
