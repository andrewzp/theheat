#!/usr/bin/env python3
"""Download one retained descriptor document to a new private Gist backup directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.evaluation.file_boundary import FileBoundaryError
from src.storage.gist_backup import backup_gists, GistBackupError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptors", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if threading.active_count() != 1:
            raise GistBackupError("backup_requires_standalone_cli")
        result = backup_gists(args.descriptors, args.output)
    except (GistBackupError, FileBoundaryError, OSError) as error:
        code = (
            str(error)
            if isinstance(error, (GistBackupError, FileBoundaryError))
            else "backup_local_io_refused"
        )
        print(json.dumps(dict(status="incomplete", code=code)))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
